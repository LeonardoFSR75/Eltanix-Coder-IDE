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

Testes não precisam de Postgres/Redis reais no ar: `db/session.py::init_engine()` é
preguiçoso (não conecta até a primeira query), e nenhum teste da suíte hoje exercita
`hybrid_search`/DB de verdade — são todos unitários ou contra `TestClient`. Se adicionar
um teste que precisa de Postgres real, isso é uma mudança de categoria, não o padrão.

## Estrutura

| Pacote | O quê |
|---|---|
| `router/` | Única porta de saída para LLM — engine, adaptadores por provedor, catálogo YAML, health/circuit breaker (Redis), custo (`RequestLog`) |
| `agent/` | `graph.py` (LangGraph think→approve→act), `tools/` (registro + handlers), `runner.py` (sessão, worktree, streaming) |
| `context/`, `documents/`, `notes/` | As três fontes de RAG — cada uma com `store.py` (SQL/RRF), `service.py` ou `indexer.py` (orquestração) |
| `mcp/` | Cliente MCP real — `config.py`/`config_editor.py` (YAML), `client.py` (conexão stdio/HTTP), `manager.py` (registra tools no `ToolRegistry`) |
| `telemetry/` | `TraceRecorder` — buffer em memória de spans de tool/RAG (não confundir com `router/telemetry.py`, que é custo de LLM em Postgres) |
| `evals/` | Harness de hit@k/MRR contra os buscadores reais — `uv run sicoobito-eval-rag` |
| `db/` | `session.py` (engine/session_scope), `models.py`, migrações Alembic em `migrations/versions/` |
| `sandbox/` | `container.py` (Docker local) / `executor.py` (cliente do serviço isolado, ver ADR 0002) |
| `api/routes/` | Uma rota por domínio, sempre `dependencies=[AuthDep]`, sempre registrada em `api/routes/__init__.py` + `main.py::create_app` |

## Padrões a seguir em código novo

- **Serviço novo com estado** (tipo `DocumentService`, `NoteService`): instanciar uma vez
  em `main.py::lifespan`, guardar em `app.state.<nome>`, e se o agente precisa dele,
  passar também para `AgentRunner(...)` e adicionar campo em `agent/tools/base.py::ToolContext`.
- **Migração nova**: próximo número da sequência em `migrations/versions/`. Coluna
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
