import requests
import json
import time
import os
import locale
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Tenta configurar para inglês para garantir que a data saia como "Mon Dec"
try:
    locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
except:
    pass 

class PNCPImporter:
    BASE_URL_CONSULTA = "https://pncp.gov.br/api/consulta"
    BASE_URL_INTEGRACAO = "https://pncp.gov.br/api/pncp"
    
    def __init__(self, cnpj="13650403000128"):
        self.cnpj = cnpj
        self.session = self.setup_session()
        self.cooldown_time = 1.0

    def setup_session(self):
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Bot-Sincronizador-PNCP",
            "Accept": "application/json"
        })
        return session

    def _safe_request(self, url, params=None):
        try:
            time.sleep(self.cooldown_time)
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"Erro na requisição: {e}")
            return None

    def listar_contratacoes(self, data_inicial, data_final, pagina=1, modalidade=None):
        url = f"{self.BASE_URL_CONSULTA}/v1/contratacoes/publicacao"
        params = {
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "pagina": pagina,
            "tamanhoPagina": 10,
            "cnpj": self.cnpj
        }
        if modalidade:
            params["codigoModalidadeContratacao"] = modalidade
        return self._safe_request(url, params=params)

    def obter_itens_contratacao(self, cnpj, ano, sequencial):
        url = f"{self.BASE_URL_INTEGRACAO}/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
        itens_completos = []
        pagina = 1
        while True:
            params = {"pagina": pagina, "tamanhoPagina": 100}
            dados = self._safe_request(url, params=params)
            if not dados: break
            
            items_list = []
            if isinstance(dados, list): items_list = dados
            elif isinstance(dados, dict): items_list = dados.get('data') or dados.get('resultado') or []
            
            if not items_list:
                if isinstance(dados, dict) and 'numeroItem' in dados: items_list = [dados]
                else: break
                
            itens_completos.extend(items_list)
            if len(items_list) < 100: break
            pagina += 1
        return itens_completos

    def obter_resultados_item(self, cnpj, ano, sequencial, numero_item):
        url = f"{self.BASE_URL_INTEGRACAO}/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
        resultados = self._safe_request(url)
        if isinstance(resultados, list): return resultados
        if isinstance(resultados, dict): return [resultados]
        return []

    def formatar_para_html(self, contratacao, item):
        """Achata a estrutura para manter compatibilidade com o HTML antigo"""
        try:
            # Formata datas
            dt_pub_raw = contratacao.get('dataPublicacaoPncp', '')
            dt_pub_fmt = ""
            if dt_pub_raw:
                dt_obj = datetime.fromisoformat(dt_pub_raw.replace('Z', '+00:00'))
                dt_pub_fmt = dt_obj.strftime("%a %b %d %Y %H:%M:%S GMT-0300 (Brasilia Standard Time)")

            # Pega vencedor do primeiro resultado se existir
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
                    dt_res_obj = datetime.fromisoformat(dt_res_raw.replace('Z', '+00:00'))
                    data_resultado_fmt = dt_res_obj.strftime("%a %b %d %Y %H:%M:%S GMT-0300 (Brasilia Standard Time)")

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
                "linkPNCP": f"https://pncp.gov.br/app/editais/{contratacao.get('orgaoEntidade', {}).get('cnpj')}/{contratacao.get('anoCompra')}/{contratacao.get('sequencialCompra')}",
                "processo": contratacao.get('processo', ""),
                "dataPublicacao": dt_pub_fmt,
                "dataResultado": data_resultado_fmt
            }
        except Exception as e:
            print(f"Erro na formatação: {e}")
            return None

    def processar_contratacao_completa(self, contratacao):
        try:
            cnpj_orgao = contratacao['orgaoEntidade']['cnpj']
            ano = contratacao['anoCompra']
            sequencial = contratacao['sequencialCompra']
            
            print(f"  -> Detalhando {ano}/{sequencial}...")
            itens = self.obter_itens_contratacao(cnpj_orgao, ano, sequencial)
            
            itens_achatados = []
            for item in itens:
                num = item.get('numeroItem')
                if num:
                    item['resultados_vencedores'] = self.obter_resultados_item(cnpj_orgao, ano, sequencial, num)
                
                # Cria uma entrada para cada item no formato antigo
                item_formatado = self.formatar_para_html(contratacao, item)
                if item_formatado:
                    itens_achatados.append(item_formatado)
            
            return itens_achatados
        except Exception as e:
            print(f"Erro no detalhamento: {e}")
            return []

    def importar_tudo(self, d_ini, d_fim):
        todos_resultados = []
        modalidades = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]
        
        atual = datetime.strptime(d_ini, "%Y%m%d")
        fim_obj = datetime.strptime(d_fim, "%Y%m%d")
        
        while atual <= fim_obj:
            bloco_fim = min(atual + timedelta(days=14), fim_obj)
            s_ini, s_fim = atual.strftime("%Y%m%d"), bloco_fim.strftime("%Y%m%d")
            print(f"\n--- Periodo: {s_ini} a {s_fim} ---")
            
            for mod in modalidades:
                pagina = 1
                while True:
                    dados = self.listar_contratacoes(s_ini, s_fim, pagina, mod)
                    if not dados or 'data' not in dados or not dados['data']: break
                    
                    for contratacao in dados['data']:
                        novos_itens = self.processar_contratacao_completa(contratacao)
                        todos_resultados.extend(novos_itens)
                    
                    if pagina >= dados.get('totalPaginas', 1): break
                    pagina += 1
            atual = bloco_fim + timedelta(days=1)
        return todos_resultados

# --- LOGICA PRINCIPAL ---
FILE_NAME = 'dados.json'

def main():
    dados_carregados = []
    is_dict_format = False
    full_json_data = {}

    if os.path.exists(FILE_NAME):
        with open(FILE_NAME, 'r', encoding='utf-8') as f:
            try:
                content = json.load(f)
                if isinstance(content, list):
                    dados_carregados = content
                    is_dict_format = False
                elif isinstance(content, dict):
                    full_json_data = content
                    dados_carregados = content.get('data', [])
                    is_dict_format = True
            except Exception as e:
                print(f"Erro ao ler JSON: {e}")

    # MODIFICAÇÃO: Busca dos últimos 360 dias
    data_hoje = datetime.now()
    data_inicio_busca = (data_hoje - timedelta(days=90)).strftime("%Y%m%d")
    data_fim_busca = data_hoje.strftime("%Y%m%d")
    
    print(f"Iniciando sincronizacao de {data_inicio_busca} ate {data_fim_busca} (ultimos 90 dias)...")
    importer = PNCPImporter()
    novos_dados = importer.importar_tudo(data_inicio_busca, data_fim_busca)

    if novos_dados:
        # Remove duplicatas baseado em chave única (ano + compra + itemNo)
        chaves_existentes = set()
        for item in dados_carregados:
            chave = f"{item.get('ano')}_{item.get('compra')}_{item.get('itemNo')}"
            chaves_existentes.add(chave)
        
        novos_dados_unicos = []
        for item in novos_dados:
            chave = f"{item.get('ano')}_{item.get('compra')}_{item.get('itemNo')}"
            if chave not in chaves_existentes:
                novos_dados_unicos.append(item)
                chaves_existentes.add(chave)
        
        if novos_dados_unicos:
            if is_dict_format:
                full_json_data['data'] = dados_carregados + novos_dados_unicos
                full_json_data['totalRegistros'] = len(full_json_data['data'])
                full_json_data['geradoEm'] = datetime.now().isoformat()
                dados_finais = full_json_data
            else:
                dados_finais = dados_carregados + novos_dados_unicos
                
            with open(FILE_NAME, 'w', encoding='utf-8') as f:
                json.dump(dados_finais, f, indent=4, ensure_ascii=False)
            print(f"\nSucesso! {len(novos_dados_unicos)} novos registros adicionados.")
        else:
            print("\nNenhuma nova contratacao encontrada (todas ja existiam).")
    else:
        print("\nNenhuma nova contratacao encontrada.")

if __name__ == "__main__":
    main()

