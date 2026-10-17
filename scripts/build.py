import json,re,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
DATA.mkdir(parents=True,exist_ok=True)
def load(p,default):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return default
def key(item):
    url=item.get('linkPNCP','')
    m=re.search(r'/editais/(\d{14})/(\d{4})/(\d+)',url)
    return '-'.join(m.groups()) if m else None
def main():
    raw=load(ROOT/'dados.json',[])
    rows=raw.get('data',[]) if isinstance(raw,dict) else raw
    groups={}
    for row in rows:
        k=key(row)
        if not k or not k.startswith('13650403000128-'):continue
        groups.setdefault(k,[]).append(row)
    index=[]
    for k,items in groups.items():
        first=items[0]; cnpj,ano,seq=k.split('-')
        # Não somar estimativas como valor global: itens podem conter resultados parciais.
        entry={'id':k,'ano':int(ano),'sequencial':int(seq),'numero':first.get('compra'),'processo':first.get('processo'),'modalidade':first.get('modalidade'),'objeto':first.get('objeto'),'orgao':first.get('orgao'),'dataPublicacao':first.get('dataPublicacao'),'linkPNCP':first.get('linkPNCP'),'totalItens':len(items),'itensComResultado':sum(1 for i in items if i.get('vencedor') and i.get('vencedor')!='SEM RESULTADO')}
        index.append(entry)
        (DATA/f'{k}.json').write_text(json.dumps({'contratacao':entry,'itens':items},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    index.sort(key=lambda x:(x['ano'],x['sequencial']),reverse=True)
    (DATA/'contratacoes.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    status=load(DATA/'status.json',{})
    status.update({'geradoEm':datetime.now(timezone.utc).isoformat(),'contratacoes':len(index),'itens':sum(map(len,groups.values())),'fonte':'dados.json (projeto original); documentos consultados separadamente','cobertura':'Base histórica existente; não equivale a cobertura integral do PNCP'})
    (DATA/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Gerados {len(index)} processos e {sum(map(len,groups.values()))} itens')
if __name__=='__main__':main()
