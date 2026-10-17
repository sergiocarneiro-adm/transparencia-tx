# Portal de Transparência — PNCP — Teixeira de Freitas

Projeto **separado** do painel original. Fonte histórica: `pncp-main.zip`, `dados.json` com 15.656 itens. O arquivo e os scripts originais estão preservados (`legado/`). CNPJ exclusivo: **13.650.403/0001-28**.

## Publicação

1. Crie um **novo** repositório GitHub (não substitua o original).
2. Envie o conteúdo desta pasta, inclusive `.github/`, `data/` e `legado/`.
3. Em Settings → Pages, escolha Deploy from a branch → main → / (root).
4. Em Settings → Actions → General, conceda `Read and write permissions` ao GitHub Actions, quando disponível.
5. Em Actions → Atualizar Portal PNCP → Run workflow, execute manualmente.
6. O portal exibirá dados históricos imediatamente; anexos são consultados progressivamente (30 processos por execução).

## Execução local

```bash
pip install -r requirements.txt
python scripts/build.py
python scripts/anexos.py  # requer internet
python scripts/sync.py    # requer internet
python -m http.server 8000
```

Acesse http://localhost:8000. Não abra `index.html` diretamente com file:// (fetch de JSON pode ser bloqueado).

## Arquitetura

- `dados.json`: **base histórica original**, preservada como fonte para o índice; atualizações incrementais são adicionadas.
- `legado/`: cópias dos scripts originais; não são executados automaticamente.
- `scripts/build.py`: agrupa itens pelo identificador PNCP (CNPJ/ano/sequencial) e gera índice e detalhes.
- `scripts/sync.py`: coleta incremental por CNPJ, com limite de requisições, espera em HTTP 429 e cursor.
- `scripts/anexos.py`: consulta documentos em lotes, sem baixar binários, mantendo links do PNCP.
- `data/contratacoes.json`: índice leve do portal.
- `data/processos/*.json`: itens e resultados por processo.
- `data/anexos/*.json`: lista de documentos por processo.
- `data/status.json`: estatísticas da geração.
- `data/cursor.json`: progresso de sincronização.

## Limitações e cautelas

- Os 15.656 registros são **itens**, não contratações distintas. O acervo histórico não garante integralidade do PNCP.
- Resultados legados registram somente o primeiro vencedor por item, conforme o código original.
- O coletor incremental não substitui uma reconciliação periódica de retificações e resultados de processos antigos.
- A coleta de itens com 100 ou mais registros pausa para evitar publicação parcial; demanda implementação de paginação completa.
- O coletor consulta a API por CNPJ usando estratégia do projeto anterior; disponibilidade e comportamento devem ser testados no ambiente real.
- Documentos são disponibilizados apenas quando a API retorna links ou sequenciais válidos. O portal mantém acesso ao PNCP como alternativa.
- Contratos e aditivos têm endpoints próprios e não estão incluídos nesta versão; não devem ser apresentados como sincronizados.
- GitHub Pages é uma hospedagem estática; os arquivos JSON são públicos. Evite adicionar informações pessoais ou documentos não destinados à divulgação.
- O workflow usa limite de 45 minutos; revise limites e cotas antes de ampliar.
