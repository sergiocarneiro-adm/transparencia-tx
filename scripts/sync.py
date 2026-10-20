"""Sincronização PNCP por blocos de datas (lógica do importador original), com cursor seguro."""
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
RAW = ROOT / 'dados.json'
CURSOR = DATA / 'cursor.json'
CNPJ = str(CFG['cnpj']).replace('.', '').replace('/', '').replace('-', '')
BASE = 'https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao'
API = 'https://pncp.gov.br/api/pncp/v1'
MODALIDADES = [int(x) for x in CFG.get('modalidades_pncp', [1,2,3,4,5,6,8,9,10,11,12,13])]
MAX_CALLS = int(CFG.get('max_requisicoes_por_execucao', 90))
PAUSE_SECONDS = float(CFG.get('intervalo_segundos', 2.5))
BLOCK_DAYS = min(15, max(1, int(CFG.get('bloco_dias_sync', 15))))
LOOKBACK_DAYS = max(1, int(CFG.get('janela_dias_sync', 14)))

class ControlledPause(Exception):
    pass

class Client:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({'Accept': 'application/json', 'User-Agent': 'PortalTransparenciaMunicipal/1.0'})
        self.calls = 0

    def get(self, url, params=None, allow_404=False):
        for attempt in range(4):
            if self.calls >= MAX_CALLS:
                raise ControlledPause('limite de requisições por execução')
            time.sleep(PAUSE_SECONDS)
            self.calls += 1
            try:
                response = self.s.get(url, params=params, timeout=35)
                if response.status_code in (429, 500, 502, 503, 504):
                    delay = min(90, 10 * (2 ** attempt))
                    try:
                        delay = max(delay, min(120, int(response.headers.get('Retry-After', '0'))))
                    except ValueError:
                        pass
                    print(f'HTTP {response.status_code}; aguardando {delay}s', flush=True)
                    time.sleep(delay)
                    continue
                if response.status_code == 204 or (allow_404 and response.status_code == 404):
                    return []
                response.raise_for_status()
                return response.json() if response.content.strip() else []
            except (requests.RequestException, ValueError) as exc:
                if attempt == 3:
                    raise RuntimeError(f'Falha de API em {url}: {exc}') from exc
                time.sleep(min(60, 5 * (2 ** attempt)))
        raise ControlledPause('API temporariamente indisponível; retomada pendente')

    def items(self, year, seq):
        output = []
        page = 1
        while True:
            payload = self.get(f'{API}/orgaos/{CNPJ}/compras/{year}/{seq}/itens',
                               {'pagina': page, 'tamanhoPagina': 100})
            chunk = unpack_list(payload)
            output.extend(chunk)
            if not chunk or (isinstance(payload, dict) and payload.get('totalPaginas') is not None and page >= int(payload['totalPaginas'])) or (len(chunk) < 100 and not (isinstance(payload, dict) and payload.get('totalPaginas') is not None)):
                return output
            page += 1

    def results(self, year, seq, number):
        payload = self.get(f'{API}/orgaos/{CNPJ}/compras/{year}/{seq}/itens/{number}/resultados', allow_404=True)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return unpack_list(payload) if 'data' in payload or 'resultado' in payload else [payload]
        raise RuntimeError('Resposta inesperada para resultados')

def unpack_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        result = payload.get('data') if 'data' in payload else payload.get('resultado', [])
        if isinstance(result, list):
            return result
    raise RuntimeError('Formato inesperado de lista na API')

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write_json(path, payload):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(path)

def main():
    if not RAW.exists():
        raise RuntimeError('dados.json ausente: sincronização cancelada para proteger a base histórica')
    raw = read_json(RAW)
    rows = raw.get('data') if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise RuntimeError('dados.json não contém lista válida de registros')
    if not (ROOT / 'legado' / 'automacao_pncp.py').exists():
        raise RuntimeError('legado/automacao_pncp.py ausente; é necessário para formatar os itens')
    spec = spec_from_file_location('pncp_legacy', ROOT / 'legado' / 'automacao_pncp.py')
    legacy = module_from_spec(spec)
    spec.loader.exec_module(legacy)
    importer = legacy.PNCPImporter(cnpj=CNPJ)
    client = Client()
    today = date.today()
    cursor = read_json(CURSOR) if CURSOR.exists() else {}
    # Compatibilidade com cursor antigo: retoma a data ainda não concluída.
    start = date.fromisoformat(cursor.get('blocoInicio', cursor.get('data', (today - timedelta(days=LOOKBACK_DAYS)).isoformat())))
    if start > today:
        start = today - timedelta(days=LOOKBACK_DAYS)
    end = min(start + timedelta(days=BLOCK_DAYS - 1), today)
    if 'blocoFim' in cursor:
        try:
            saved_end = date.fromisoformat(cursor['blocoFim'])
            if start <= saved_end <= today:
                end = saved_end
        except (ValueError, TypeError):
            pass
    modality = int(cursor.get('modalidade', MODALIDADES[0]))
    page = max(1, int(cursor.get('pagina', 1)))
    if modality not in MODALIDADES:
        modality, page = MODALIDADES[0], 1
    known = {(r.get('linkPNCP'), str(r.get('itemNo'))) for r in rows}
    known_processes = {r.get('linkPNCP') for r in rows}
    added_items = 0
    added_processes = 0
    pages = 0
    empty_pages = 0
    reason = 'completo'

    def save_state():
        nonlocal raw
        if isinstance(raw, dict):
            raw['data'] = rows
            raw['totalRegistros'] = len(rows)
            raw['geradoEm'] = datetime.now(timezone.utc).isoformat()
        else:
            raw = rows
        write_json(RAW, raw)
        write_json(CURSOR, {
            'data': start.isoformat(), 'blocoInicio': start.isoformat(), 'blocoFim': end.isoformat(),
            'modalidade': modality, 'pagina': page, 'ultimaExecucao': datetime.now(timezone.utc).isoformat(),
            'motivo': reason, 'requisicoes': client.calls, 'novosItens': added_items,
            'novosProcessos': added_processes
        })

    print(f'Consulta por blocos: {start} a {end}; modalidade inicial {modality}; página {page}', flush=True)
    try:
        while start <= today:
            print(f'Consultando {start} a {end}; modalidade {modality}; página {page}', flush=True)
            params = {'dataInicial': start.strftime('%Y%m%d'), 'dataFinal': end.strftime('%Y%m%d'),
                      'codigoModalidadeContratacao': modality, 'cnpj': CNPJ,
                      'pagina': page, 'tamanhoPagina': 10}
            response = client.get(BASE, params)
            records = unpack_list(response)
            pages += 1
            if not records:
                empty_pages += 1
            total = int(response.get('totalPaginas') or 1) if isinstance(response, dict) else 1
            # Página atômica: não avança o cursor antes de todos os processos serem obtidos.
            page_items = []
            page_processes = set()
            for rec in records:
                org = rec.get('orgaoEntidade') or {}
                if str(org.get('cnpj', '')).replace('.', '').replace('/', '').replace('-', '') != CNPJ:
                    continue
                year, seq = rec.get('anoCompra'), rec.get('sequencialCompra')
                if not year or not seq:
                    continue
                link = f'https://pncp.gov.br/app/editais/{CNPJ}/{year}/{seq}'
                if link in known_processes or link in page_processes:
                    continue
                items = client.items(year, seq)
                if not items:
                    raise RuntimeError(f'Processo {year}/{seq} sem itens; página será reconsultada')
                formatted = []
                for item in items:
                    number = item.get('numeroItem')
                    if number is not None:
                        item['resultados_vencedores'] = client.results(year, seq, number)
                    flat = importer.formatar_para_html(rec, item)
                    if flat is None:
                        raise RuntimeError(f'Erro ao formatar processo {year}/{seq}')
                    formatted.append(flat)
                page_items.extend(formatted)
                page_processes.add(link)
            for item in page_items:
                key = (item.get('linkPNCP'), str(item.get('itemNo')))
                if key not in known:
                    rows.append(item)
                    known.add(key)
                    added_items += 1
            known_processes.update(page_processes)
            added_processes += len(page_processes)
            if page < total:
                page += 1
            else:
                idx = MODALIDADES.index(modality)
                if idx + 1 < len(MODALIDADES):
                    modality, page = MODALIDADES[idx + 1], 1
                else:
                    start = end + timedelta(days=1)
                    end = min(start + timedelta(days=BLOCK_DAYS - 1), today)
                    modality, page = MODALIDADES[0], 1
            save_state()
        # Terminou o ciclo: reconsultar a janela recente na próxima execução.
        start = today - timedelta(days=LOOKBACK_DAYS)
        end = min(start + timedelta(days=BLOCK_DAYS - 1), today)
        modality, page = MODALIDADES[0], 1
        reason = 'ciclo completo; próxima execução revisará a janela recente'
        save_state()
    except ControlledPause as exc:
        reason = f'pausa controlada: {exc}'
        save_state()
        print(reason, flush=True)
    except Exception as exc:
        reason = f'ERRO: {exc}'
        save_state()
        print(reason, file=sys.stderr, flush=True)
        raise
    finally:
        print(f'Requisições: {client.calls}; páginas: {pages}; páginas vazias: {empty_pages}; '
              f'novos processos: {added_processes}; novos itens: {added_items}; status: {reason}', flush=True)

if __name__ == '__main__':
    main()
