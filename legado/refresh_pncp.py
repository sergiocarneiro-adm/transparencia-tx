import requests
import json
import time
import os
import locale
import re
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Tenta configurar para inglês para garantir que a data saia como "Mon Dec"
try:
    locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
except:
    pass 

class PNCPRefresher:
    BASE_URL_CONSULTA = "https://pncp.gov.br/api/consulta"
    BASE_URL_INTEGRACAO = "https://pncp.gov.br/api/pncp"
    
    def __init__(self, cnpj="13650403000128"):
        self.cnpj = self.limpar_cnpj(cnpj)
        self.session = self.setup_session()
        self.cooldown_time = 1.5 # Delay para evitar bloqueio em varreduras longas

    def limpar_cnpj(self, cnpj):
        return re.sub(r'\D', '', str(cnpj))

    def setup_session(self):
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PNCP-Explorer-Refresher/1.5",
            "Accept": "application/json"
        })
        return session

    def _safe_request(self, url, params=None):
        try:
            time.sleep(self.cooldown_time)
            response = self.session.get(url, params=params, timeout=30, allow_redirects=True)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 204:
                return None
            elif response.status_code == 404:
                return None
            else:
                print(f"  [!] Aviso: Status {response.status_code} na URL: {url}")
                return None
        except Exception as e:
            print(f"  [!] Erro na requisição: {e}")
            return None

    def obter_dados_contratacao(self, cnpj, ano, sequencial):
        cnpj_limpo = self.limpar_cnpj(cnpj)
        url = f"{self.BASE_URL_CONSULTA}/v1/orgaos/{cnpj_limpo}/compras/{ano}/{sequencial}"
        return self._safe_request(url)

    def obter_item_especifico(self, cnpj, ano, sequencial, numero_item):
        cnpj_limpo = self.limpar_cnpj(cnpj)
        url = f"{self.BASE_URL_INTEGRACAO}/v1/orgaos/{cnpj_limpo}/compras/{ano}/{sequencial}/itens/{numero_item}"
        return self._safe_request(url)

    def obter_resultados_item(self, cnpj, ano, sequencial, numero_item):
        cnpj_limpo = self.limpar_cnpj(cnpj)
        url = f"{self.BASE_URL_INTEGRACAO}/v1/orgaos/{cnpj_limpo}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
        resultados = self._safe_request(url)
        if isinstance(resultados, list): return resultados
        if isinstance(resultados, dict): return [resultados]
        return []

    def formatar_para_html(self, contratacao, item):
        try:
            dt_pub_raw = contratacao.get('dataPublicacaoPncp', '')
            dt_pub_fmt = ""
            if dt_pub_raw:
                try:
                    dt_obj = datetime.fromisoformat(dt_pub_raw.replace('Z', '+00:00'))
                    dt_pub_fmt = dt_obj.strftime("%a %b %d %Y %H:%M:%S GMT-0300 (Brasilia Standard Time)")
                except: pass

            vencedor_nome = "SEM RESULTADO"
            vencedor_cnpj = ""
            valor_unit_homologado = 0
            valor_total_homologado = 0
            qtd_homologada = 0
            data_resultado_fmt = ""

            resultados = item.get('resultados_vencedores', [])
            if resultados:
                res = resultados[0]
                vencedor_nome = res.get('nomeRazaoSocialFornecedor', "SEM RESULTADO")
                vencedor_cnpj = res.get('niFornecedor', "")
                valor_unit_homologado = res.get('valorUnitarioHomologado', 0)
                valor_total_homologado = res.get('valorTotalHomologado', 0)
                qtd_homologada = res.get('quantidadeHomologada', 0)
                dt_res_raw = res.get('dataResultado', '')
                if dt_res_raw:
                    try:
                        dt_res_obj = datetime.fromisoformat(dt_res_raw.replace('Z', '+00:00'))
                        data_resultado_fmt = dt_res_obj.strftime("%a %b %d %Y %H:%M:%S GMT-0300 (Brasilia Standard Time)")
                    except: pass

            return {
                "orgao": contratacao.get('orgaoEntidade', {}).get('razaoSocial', ""),
                "ano": contratacao.get('anoCompra'),
                "compra": contratacao.get('numeroCompra', ""),
                "modalidade": contratacao.get('modalidadeNome', ""),
                "objeto": contratacao.get('objetoCompra', ""),
                "itemNo": item.get('numeroItem'),
                "descricao": item.get('descricao', ""),
                "quantidade": item.get('quantidade', 0),
                "unidade": item.get('unidadeMedida', ""),
                "valorUnitEstimado": item.get('valorUnitarioEstimado', 0),
                "valorTotalEstimado": item.get('valorTotal', 0),
                "vencedor": vencedor_nome,
                "cnpjVencedor": vencedor_cnpj,
                "valorUnitHomologado": valor_unit_homologado,
                "valorTotalHomologado": valor_total_homologado,
                "qtdHomologada": qtd_homologada,
                "situacaoItem": item.get('situacaoCompraItemNome', ""),
                "linkPNCP": f"https://pncp.gov.br/app/editais/{self.limpar_cnpj(contratacao.get('orgaoEntidade', {}).get('cnpj'))}/{contratacao.get('anoCompra')}/{contratacao.get('sequencialCompra')}",
                "processo": contratacao.get('processo', ""),
                "dataPublicacao": dt_pub_fmt,
                "dataResultado": data_resultado_fmt
            }
        except Exception as e:
            print(f"Erro na formatação: {e}")
            return None

def salvar_json(content, file_name):
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(content, f, indent=4, ensure_ascii=False)

def main():
    FILE_NAME = 'dados.json'
    if not os.path.exists(FILE_NAME):
        print(f"Arquivo {FILE_NAME} não encontrado.")
        return

    with open(FILE_NAME, 'r', encoding='utf-8') as f:
        content = json.load(f)
    
    is_dict = isinstance(content, dict)
    dados_lista = content.get('data', []) if is_dict else content
    
    if not dados_lista:
        print("Nenhum dado encontrado no JSON.")
        return

    refresher = PNCPRefresher()
    
    # Status pendentes
    status_para_atualizar = ["Em andamento", "Publicada", "Divulgada", "Em Aberto"]
    
    indices_para_atualizar = [
        idx for idx, item in enumerate(dados_lista) 
        if item.get('situacaoItem') in status_para_atualizar
    ]

    total_pendentes = len(indices_para_atualizar)
    if total_pendentes == 0:
        print("Nenhum item com status pendente encontrado.")
        return

    print(f"Iniciando varredura total para {total_pendentes} itens pendentes...")
    
    alteracoes = 0
    processados = 0
    cache_compras = {}

    for idx in indices_para_atualizar:
        item_antigo = dados_lista[idx]
        processados += 1
        
        try:
            link = item_antigo.get('linkPNCP', '')
            match = re.search(r'editais/(\d+)/(\d+)/(\d+)', link)
            if not match:
                continue
                
            cnpj_orgao, ano, sequencial = match.groups()
            num_item = item_antigo.get('itemNo')

            if sequencial not in cache_compras:
                cache_compras[sequencial] = refresher.obter_dados_contratacao(cnpj_orgao, ano, sequencial)
            
            contratacao_nova = cache_compras[sequencial]
            if not contratacao_nova:
                continue

            item_novo_bruto = refresher.obter_item_especifico(cnpj_orgao, ano, sequencial, num_item)
            if not item_novo_bruto:
                continue

            item_novo_bruto['resultados_vencedores'] = refresher.obter_resultados_item(cnpj_orgao, ano, sequencial, num_item)
            item_atualizado = refresher.formatar_para_html(contratacao_nova, item_novo_bruto)
            
            if item_atualizado:
                if (item_atualizado['situacaoItem'] != item_antigo['situacaoItem'] or 
                    item_atualizado['vencedor'] != item_antigo['vencedor'] or
                    item_atualizado['valorTotalHomologado'] != item_antigo['valorTotalHomologado']):
                    
                    print(f"[{processados}/{total_pendentes}] ATUALIZADO: {item_antigo['compra']} Item {num_item} -> {item_atualizado['situacaoItem']}")
                    dados_lista[idx] = item_atualizado
                    alteracoes += 1
                else:
                    if processados % 50 == 0:
                        print(f"[{processados}/{total_pendentes}] Verificado (sem mudanças)...")

            # Salvamento progressivo a cada 50 itens para não perder progresso
            if processados % 50 == 0 and alteracoes > 0:
                if is_dict:
                    content['data'] = dados_lista
                    content['totalRegistros'] = len(dados_lista)
                    content['geradoEm'] = datetime.now().isoformat()
                else:
                    content = dados_lista
                salvar_json(content, FILE_NAME)
                print(f"  >> Progresso salvo ({alteracoes} alterações até agora).")

        except Exception as e:
            print(f"  [!] Erro ao processar {item_antigo.get('compra')}: {e}")

    # Salvamento final
    if alteracoes > 0:
        if is_dict:
            content['data'] = dados_lista
            content['totalRegistros'] = len(dados_lista)
            content['geradoEm'] = datetime.now().isoformat()
        else:
            content = dados_lista
        salvar_json(content, FILE_NAME)
        print(f"\nVarredura concluída! Total de {alteracoes} registros atualizados.")
    else:
        print("\nVarredura concluída. Nenhuma alteração detectada.")

if __name__ == "__main__":
    main()
