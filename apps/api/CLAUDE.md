# apps/api

FastAPI + SQLAlchemy async (asyncpg) + LangGraph + pgvector. Python `>=3.12,<3.13`,
gerenciado por `uv`. Ver [../CLAUDE.md](../CLAUDE.md) para invariantes de arquitetura.

## Comandos

```bash
uv sync --dev              # instalar/atualizar dependências
uv run pytest tests -q     # suíte completa — rodar sempre após mudar algo aqui
uv run ruff check src      # lint (select = E,F,I,UP,B,ASYNC,RUF)
uv run pytest tests/test_x.py -q   # um módulo específico
```

Testes não precisam de Postgres/Redis reais no ar por padrão: `db/session.py::init_engine()`
é preguiçoso (não conecta até a primeira query), e a suíte roda unitária ou contra
`TestClient`. **Exceção**: `tests/test_hybrid_search.py` exercita as três `hybrid_search`
(RRF) contra Postgres/pgvector de verdade, via a fixture `pg_session` (`conftest.py`) —
pulada automaticamente sem `DATABASE_URL_TEST` definida, então não quebra o dia a dia.
Para rodar de verdade, localmente:

```bash
# uma vez, contra o Postgres do docker-compose (porta 5403):
docker compose exec postgres psql -U sicoobito -d sicoobito -c "CREATE DATABASE sicoobito_test"
DATABASE_URL="postgresql+asyncpg://sicoobito:sicoobito@localhost:5403/sicoobito_test" uv run alembic upgrade head

# a cada vez que quiser rodar os testes de RRF:
DATABASE_URL_TEST="postgresql+asyncpg://sicoobito:sicoobito@localhost:5403/sicoobito_test" \
  uv run pytest tests/test_hybrid_search.py -q
```

`pg_session` isola cada teste por transação com rollback no teardown — não precisa recriar
o banco nem rodar migração de novo entre execuções.

## Explorar a API na mão

`bruno/` tem uma coleção [Bruno](https://www.usebruno.com/) (auth + agent) para bater na
API sem escrever `curl` — abra a pasta como coleção, selecione o ambiente `local`, ver
`bruno/README.md`.

## Estrutura

| Pacote | O quê |
|---|---|
| `router/` | Única porta de saída para LLM — engine, adaptadores por provedor, catálogo YAML, health/circuit breaker (Redis), custo (`RequestLog`) |
| `agent/` | `graph.py` (LangGraph think→approve→act), `tools/` (registro + handlers), `runner.py` (sessão, worktree, streaming), `coordinator.py` (multiagente) |
| `context/`, `documents/`, `notes/`, `graphify/` | As quatro fontes de RAG — cada uma com `store.py`, `service.py`/`indexer.py` ou `graph_rag.py` (expansão via CTE/GQL) |
| `graphify/` | Engine de Grafo de Conhecimento: extração L1 (Wikilinks, Tags, AST/TS Imports), arestas L2/L3, `GraphStore` (PostgreSQL `graph_node`/`graph_edge`), `GraphAnalytics` e `GraphRAGQueryEngine` |
| `notes/` | Segundo Cérebro: `store.py`, `service.py` (resolução de wikilinks `[[...]]`, fatiamento consciente de prosa e indexação vetorial) |
| `mcp/` | Cliente MCP real — `config.py`/`config_editor.py` (YAML), `client.py` (conexão stdio/HTTP), `manager.py` (registra tools no `ToolRegistry`) |
| `telemetry/` | `TraceRecorder` — buffer em memória de spans de tool/RAG (não confundir com `router/telemetry.py`, que é custo de LLM em Postgres) |
| `evals/` | Harness de hit@k/MRR contra os buscadores reais — `uv run sicoobito-eval-rag` |
| `db/` | `session.py` (engine/session_scope), `models.py`, migrações Alembic em `alembic/versions/` |
| `sandbox/` | `container.py` (Docker local) / `executor.py` (cliente do serviço isolado, ver ADR 0002) |
| `analytics/` | Subsistema de ML & Auto-Diagnóstico — clusterização K-Means/DBScan de trajetórias de falhas, gerador de correções e propostas de diffs |
| `api/routes/` | Uma rota por domínio, sempre `dependencies=[AuthDep]`, sempre registrada em `api/routes/__init__.py` + `main.py::create_app` |

## Uso Obrigatório do Conhecimento por Agentes de IA

Agentes e desenvolvedores trabalhando nesta API **devem** consultar o grafo e as notas antes de propor alterações estruturais:
- **Obsidian Vault**: `graphify-out/obsidian/` (MOCs temáticos em `00 - 🏠 Painel & MOCs/` e ADRs em `01 - 📑 Documentos & ADRs/`).
- **Graph Search**: Utilizar a ferramenta `graph_search` ou a engine `GraphStore` para rastrear relacionamentos de dependência e imports antes de refatorar rotas, modelos ou serviços.

## Padrões a seguir em código novo

- **Serviço novo com estado** (tipo `DocumentService`, `NoteService`): instanciar uma vez
  em `main.py::lifespan`, guardar em `app.state.<nome>`, e se o agente precisa dele,
  passar também para `AgentRunner(...)` e adicionar campo em `agent/tools/base.py::ToolContext`.
- **Migração nova**: próximo número da sequência em `alembic/versions/`. Coluna
  `GENERATED ALWAYS AS (to_tsvector(...)) STORED` e índice HNSW pgvector não saem de
  `op.create_table` — usar `op.execute()` com o DDL cru (ver `0005_documents.py` como
  exemplo).
- **Ferramenta nova do agente**: decorar com `@tool(name=..., risk=RiskClass.READ|WRITE|EXEC, ...)`
  em `agent/tools/`, handler assina `(ctx: ToolContext, args: dict) -> ToolResult`. A
  classe de risco é a única coisa que decide aprovação — não adicionar checagem própria.
- **Rota nova**: `APIRouter(prefix="/api/<domínio>", dependencies=[AuthDep])`, registrar em
  `api/routes/__init__.py` e `main.py`. Acesso a estado global via `getattr(request.app.state, "x", None)`
  com 503 se `None` (ver `api/routes/mcp.py::_manager` como modelo).
- **Config declarativa nova**: mesma dupla `config.py` (leitura, pydantic) +
  `config_editor.py` (escrita, ruamel.yaml) que `mcp/` já usa — não reinventar.
