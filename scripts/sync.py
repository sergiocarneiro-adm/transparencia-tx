"""Coleta incremental e segura. Preserva dados.json e só grava resultados completos por processo."""
import json,os,time,random,re,sys
from pathlib import Path
from datetime import date,timedelta,datetime,timezone
import requests
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config.json').read_text())
DATA=ROOT/'data';DATA.mkdir(exist_ok=True)
CURSOR=DATA/'cursor.json';RAW=ROOT/'dados.json'
CNPJ=CFG['cnpj']; BASE='https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao'; API='https://pncp.gov.br/api/pncp/v1'
MODALIDADES=[int(x) for x in CFG.get('modalidades_pncp',list(range(1,14)))]
MAX=int(CFG.get('max_requisicoes_por_execucao',90)); PAUSE=float(CFG.get('intervalo_segundos',2.5))
class Pause(Exception):pass
class Collector:
 def __init__(self):self.session=requests.Session();self.session.headers.update({'Accept':'application/json','User-Agent':'PortalTransparenciaMunicipal/1.0'});self.calls=0;self.errors=[]
 def get(self,url,params=None):
  if self.calls>=MAX:raise Pause('Limite de requisições por execução')
  for attempt in range(4):
   if self.calls>=MAX:raise Pause('Limite de requisições por execução')
   time.sleep(PAUSE);self.calls+=1
   try:
    r=self.session.get(url,params=params,timeout=35)
    if r.status_code in (429,500,502,503,504):
     wait=min(90,10*2**attempt)
     try:wait=max(wait,min(120,int(r.headers.get('Retry-After','0'))))
     except ValueError:pass
     print(f'HTTP {r.status_code}; aguardando {wait}s');time.sleep(wait);continue
    if r.status_code==204:return []
    if r.status_code==404:raise RuntimeError(f'HTTP 404 na API: {r.url}')
    r.raise_for_status()
    if not r.content.strip():return []
    return r.json()
   except (requests.RequestException,ValueError) as e:
    if attempt==3:raise RuntimeError(f'{url}: {e}') from e
    time.sleep(min(60,5*2**attempt))
  raise Pause('API indisponível ou limitando requisições; retomada posterior')
 def items(self,ano,seq):
  output=[];pagina=1
  while True:
   data=self.get(f'{API}/orgaos/{CNPJ}/compras/{ano}/{seq}/itens',{'pagina':pagina,'tamanhoPagina':100})
   chunk=data if isinstance(data,list) else (data.get('data') or data.get('resultado') or []) if isinstance(data,dict) else []
   if not isinstance(chunk,list):raise RuntimeError('Resposta de itens inválida')
   output.extend(chunk)
   if isinstance(data,dict):
    total=data.get('totalPaginas')
    if total is not None:
     if pagina>=int(total):break
    elif len(chunk)<100:break
   elif len(chunk)<100:break
   if not chunk:break
   pagina+=1
  return output
 def results(self,ano,seq,n):
  data=self.get(f'{API}/orgaos/{CNPJ}/compras/{ano}/{seq}/itens/{n}/resultados')
  return data if isinstance(data,list) else ([data] if isinstance(data,dict) else [])
def load(path,default):
 try:return json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):return default
def main():
 from importlib.util import spec_from_file_location,module_from_spec
 spec=spec_from_file_location('original',ROOT/'legado'/'automacao_pncp.py');mod=module_from_spec(spec);spec.loader.exec_module(mod)
 collector=Collector();old=load(RAW,{'data':[]});rows=old.get('data',[]) if isinstance(old,dict) else old
 existing={(r.get('linkPNCP'),str(r.get('itemNo'))) for r in rows}
 cursor=load(CURSOR,{})
 today=date.today();window=int(CFG.get('janela_dias',7))
 # Reconsulta a janela recente em cada ciclo concluído, para capturar publicações tardias.
 default_start=today-timedelta(days=window)
 start=date.fromisoformat(cursor.get('data',str(default_start)))
 if start>today:start=default_start
 day=start; modality=int(cursor.get('modalidade',MODALIDADES[0]));page=int(cursor.get('pagina',1))
 if modality not in MODALIDADES:modality=MODALIDADES[0];page=1
 seen=0;added=0;reason='completo';pending=[];fatal=None
 importer=mod.PNCPImporter(cnpj=CNPJ)
 try:
  while day<=today:
   params={'dataInicial':day.strftime('%Y%m%d'),'dataFinal':day.strftime('%Y%m%d'),
           'codigoModalidadeContratacao':modality,'cnpj':CNPJ,'pagina':page,'tamanhoPagina':10}
   result=collector.get(BASE,params)
   if isinstance(result,list):records=result;total=1
   elif isinstance(result,dict):
    records=result.get('data') or []
    total=int(result.get('totalPaginas') or 1)
   else:raise RuntimeError(f'Resposta inválida para {day}, modalidade {modality}')
   if not isinstance(records,list):raise RuntimeError('Lista de contratações inválida')
   # Uma página só avança quando todos os seus processos foram concluídos.
   page_pending=[]
   for rec in records:
    if str((rec.get('orgaoEntidade') or {}).get('cnpj'))!=CNPJ:continue
    ano=rec.get('anoCompra');seq=rec.get('sequencialCompra')
    if not ano or not seq:continue
    link=f'https://pncp.gov.br/app/editais/{CNPJ}/{ano}/{seq}'
    if any(r.get('linkPNCP')==link for r in rows) or any(r.get('linkPNCP')==link for r in pending):continue
    items=collector.items(ano,seq)
    if not items:raise RuntimeError(f'Processo {ano}/{seq} sem itens: tentar novamente')
    formatted=[]
    for item in items:
     if item.get('numeroItem') is not None:item['resultados_vencedores']=collector.results(ano,seq,item['numeroItem'])
     flat=importer.formatar_para_html(rec,item)
     if flat is None:raise RuntimeError(f'Falha ao formatar item do processo {ano}/{seq}')
     formatted.append(flat)
    page_pending.extend(formatted);seen+=1
   pending.extend(page_pending)
   if page<total:page+=1
   else:
    idx=MODALIDADES.index(modality)
    if idx+1<len(MODALIDADES):modality=MODALIDADES[idx+1];page=1
    else:day+=timedelta(days=1);modality=MODALIDADES[0];page=1
 except Pause as e:
  reason=f'limite: {e}';print('Pausa controlada:',reason)
 except (RuntimeError,requests.RequestException,ValueError,KeyError) as e:
  fatal=e;reason=f'ERRO: {e}';print(reason,file=sys.stderr)
 finally:
  for item in pending:
   k=(item.get('linkPNCP'),str(item.get('itemNo')))
   if k not in existing:rows.append(item);existing.add(k);added+=1
  if isinstance(old,dict):old['data']=rows;old['totalRegistros']=len(rows);old['geradoEm']=datetime.now(timezone.utc).isoformat()
  else:old=rows
  RAW.write_text(json.dumps(old,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
  if day>today and fatal is None:
   day=today-timedelta(days=window);modality=MODALIDADES[0];page=1
  CURSOR.write_text(json.dumps({'data':day.isoformat(),'modalidade':modality,'pagina':page,
   'ultimaExecucao':datetime.now(timezone.utc).isoformat(),'motivo':reason,
   'requisicoes':collector.calls,'novosItens':added},ensure_ascii=False,indent=2),encoding='utf-8')
  print(f'Requisições: {collector.calls}; novos processos: {seen}; novos itens: {added}; status: {reason}')
 if fatal is not None:sys.exit(1)
if __name__=='__main__':main()
