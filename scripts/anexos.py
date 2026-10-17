"""Consulta documentos de processos históricos em lotes limitados, com retomada."""
import json,time,os
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data';CFG=json.loads((ROOT/'config.json').read_text());LIMIT=int(CFG.get('max_anexos_por_execucao',30));PAUSE=float(CFG.get('intervalo_segundos',2.5))
(DATA/'anexos').mkdir(parents=True,exist_ok=True)
INDEX=json.loads((DATA/'contratacoes.json').read_text(encoding='utf-8'))
S=requests.Session();S.headers.update({'Accept':'application/json','User-Agent':'PortalTransparenciaMunicipal/1.0'})
def main():
 success=0;errors=[]
 for p in INDEX:
  target=DATA/'anexos'/f"{p['id']}.json"
  # Reconsultar anexos antigos periodicamente (padrão: 14 dias)
  if target.exists() and time.time()-target.stat().st_mtime < 14*86400:continue
  if success>=LIMIT:break
  url=f"https://pncp.gov.br/api/pncp/v1/orgaos/13650403000128/compras/{p['ano']}/{p['sequencial']}/arquivos"
  for retry in range(3):
   time.sleep(PAUSE)
   try:
    r=S.get(url,timeout=35)
    if r.status_code==429 or r.status_code>=500:
     time.sleep(15*(retry+1));continue
    if r.status_code in (204,404):docs=[]
    else:
     r.raise_for_status();docs=r.json()
    if isinstance(docs,dict):docs=docs.get('data') or docs.get('resultado') or []
    if not isinstance(docs,list):raise ValueError('Formato de documentos inesperado')
    # Não inventar URLs: usar campos fornecidos pela API ou endpoint oficial de download.
    output=[]
    for d in docs:
     if not isinstance(d,dict):continue
     seq=d.get('sequencialDocumento') or d.get('sequencial')
     link=d.get('url') or d.get('urlDocumento') or d.get('uri')
     if not link and seq is not None:link=f'{url}/{seq}'
     output.append({'titulo':d.get('titulo') or d.get('nome') or 'Documento','tipo':d.get('tipoDocumentoNome') or d.get('tipoDocumentoDescricao') or '', 'dataPublicacao':d.get('dataPublicacaoPncp') or d.get('dataPublicacao') or '', 'url':link})
    target.write_text(json.dumps(output,ensure_ascii=False,separators=(',',':')),encoding='utf-8');success+=1;break
   except (requests.RequestException,ValueError) as e:
    if retry==2:errors.append(f"{p['id']}: {e}")
 print(f'Anexos: {success} processos consultados; falhas: {len(errors)}')
 if errors:print('\n'.join(errors[:10]))
if __name__=='__main__':main()
