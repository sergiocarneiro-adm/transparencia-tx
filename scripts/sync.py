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
    if r.status_code in (204,404):return []
    r.raise_for_status()
    if not r.content.strip():return []
    return r.json()
   except (requests.RequestException,ValueError) as e:
    if attempt==3:raise RuntimeError(f'{url}: {e}') from e
    time.sleep(min(60,5*2**attempt))
  raise Pause('API indisponível ou limitando requisições; retomada posterior')
 def items(self,ano,seq):
  data=self.get(f'{API}/orgaos/{CNPJ}/compras/{ano}/{seq}/itens',{'pagina':1,'tamanhoPagina':100})
  if isinstance(data,list):return data
  if isinstance(data,dict):return data.get('data') or data.get('resultado') or []
  return []
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
 today=date.today();start=date.fromisoformat(cursor.get('data',str(today-timedelta(days=CFG.get('janela_dias',7)))))
 if start>today:start=today-timedelta(days=CFG.get('janela_dias',7))
 day=start; page=int(cursor.get('pagina',1));seen=0;added=0;reason='completo';pending=[]
 try:
  while day<=today:
   # consulta por CNPJ utilizada pelo projeto legado funcional
   params={'dataInicial':day.strftime('%Y%m%d'),'dataFinal':day.strftime('%Y%m%d'),'cnpj':CNPJ,'pagina':page,'tamanhoPagina':10}
   result=collector.get(BASE,params)
   records=result.get('data',[]) if isinstance(result,dict) else []
   if not records:
    day+=timedelta(days=1);page=1;continue
   for rec in records:
    if str((rec.get('orgaoEntidade') or {}).get('cnpj'))!=CNPJ:continue
    ano=rec.get('anoCompra');seq=rec.get('sequencialCompra')
    if not ano or not seq:continue
    link=f'https://pncp.gov.br/app/editais/{CNPJ}/{ano}/{seq}'
    if any(r.get('linkPNCP')==link for r in rows):continue
    items=collector.items(ano,seq)
    if len(items)>=100:
     raise Pause(f'Processo {ano}/{seq} possui >=100 itens: requer paginação completa; não publicado parcialmente')
    formatted=[]
    for item in items:
     if item.get('numeroItem') is not None:item['resultados_vencedores']=collector.results(ano,seq,item['numeroItem'])
     flat=mod.PNCPImporter(cnpj=CNPJ).formatar_para_html(rec,item)
     if flat:formatted.append(flat)
    pending.extend(formatted);seen+=1
   total=int(result.get('totalPaginas',1)) if isinstance(result,dict) else 1
   if page>=total:day+=timedelta(days=1);page=1
   else:page+=1
 except (Pause,RuntimeError,requests.RequestException,ValueError) as e:
  reason=str(e);print('Pausa controlada:',reason)
 finally:
  for item in pending:
   k=(item.get('linkPNCP'),str(item.get('itemNo')))
   if k not in existing:rows.append(item);existing.add(k);added+=1
  if isinstance(old,dict):old['data']=rows;old['totalRegistros']=len(rows);old['geradoEm']=datetime.now(timezone.utc).isoformat()
  else:old=rows
  RAW.write_text(json.dumps(old,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
  # cursor apenas avança após concluir página; em caso de interrupção durante página, ela será repetida com deduplicação
  CURSOR.write_text(json.dumps({'data':day.isoformat(),'pagina':page,'ultimaExecucao':datetime.now(timezone.utc).isoformat(),'motivo':reason,'requisicoes':collector.calls,'novosItens':added},ensure_ascii=False,indent=2),encoding='utf-8')
  print(f'Requisições: {collector.calls}; novos processos: {seen}; novos itens: {added}; status: {reason}')
if __name__=='__main__':main()
