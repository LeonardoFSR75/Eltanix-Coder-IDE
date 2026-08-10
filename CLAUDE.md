# SicoobitoCode

IDE agêntica local-first: FastAPI (`apps/api`) + Next.js (`apps/web`), Postgres+pgvector,
Redis, MinIO, tudo via Docker Compose. Ver [README.md](README.md) para a visão de produto
e como subir a stack — este arquivo é sobre como trabalhar no código.

Guias específicos: [apps/api/CLAUDE.md](apps/api/CLAUDE.md), [apps/web/CLAUDE.md](apps/web/CLAUDE.md).

## Invariantes de arquitetura (não violar sem atualizar o ADR correspondente)

- **Uma única porta de saída para LLM** (`docs/adr/0001-camada-unica-de-llm.md`): nenhum
  módulo fora de `sicoobito.router` importa `litellm`/`openai`/`anthropic`/SDK de
  provedor. Todo consumo passa por `RouterEngine.complete()`/`.embed()`.
- **Execução de comando nunca fala direto com o daemon Docker da API**
  (`docs/adr/0002-executor-isolado.md`): em produção/container, `run_command` passa pelo
  serviço `executor` isolado, autenticado por `EXECUTOR_TOKEN`. As restrições de sandbox
  (usuário não-root, `cap_drop: ALL`, rede desabilitada) são fixadas *no executor*, nunca
  recebidas por parâmetro do chamador.
- **Toda ferramenta do agente declara uma `RiskClass`** (`READ`/`WRITE`/`EXEC`) em
  `agent/tools/base.py`. `WRITE`/`EXEC` sempre param no grafo (`agent/graph.py`) esperando
  aprovação humana via `interrupt()` do LangGraph — isso é decidido pela ferramenta, nunca
  pelo chamador. Ferramentas MCP (servidores externos conectados em `/mcp`) nascem `WRITE`
  por padrão; só viram `READ` se o servidor for marcado `trust_annotations: true` e a tool
  anunciar `read_only_hint: true` — a spec do MCP é explícita que esse hint não é garantia.
- **RAG tem fontes independentes** (`context/store.py`, `documents/store.py`, `notes/store.py`,
  `graphify/store.py`) — a duplicação entre as rotinas de busca é **deliberada**, documentada
  nos próprios arquivos. Não abstrair num helper compartilhado.
- **Config declarativa em YAML + editor de round-trip** (`providers.yaml`/`routes.yaml`/
  `mcp.yaml`/`mcp_catalog.yaml`): leitura simples via `yaml.safe_load` num módulo `config.py`
  do domínio, escrita via `ruamel.yaml` num `*_editor.py` separado, para preservar
  comentários do arquivo. Espelhar esse padrão em qualquer config nova.
- **Falha de serviço opcional degrada, não derruba**: Redis fora → sem cache/circuit
  breaker; MinIO fora → upload de documento indisponível; MCP com comando inválido →
  aquele servidor marca `status: "error"`, os outros continuam. Todo `except Exception`
  nesse espírito deve logar e seguir, nunca propagar e travar o resto da plataforma.

## Comandos

```bash
# Backend — sempre depois de mudar algo em apps/api/src
cd apps/api && uv run pytest tests -q && uv run ruff check src

# Frontend — sempre depois de mudar algo em apps/web
cd apps/web && npm run typecheck && npm run build

# Stack completa (Docker Compose)
docker compose up -d --build
docker compose exec api alembic upgrade head   # nova migração
docker compose logs api -f                     # logs com structlog (JSON se LOG_JSON=1)
```

CI (`.github/workflows/ci.yml`) roda os dois primeiros blocos mais auditoria de
dependências (`pip-audit`, `npm audit --audit-level=high`) em todo push/PR na `main`.

`api` e `web` rodam com hot-reload via bind mount (`--reload` no uvicorn,
`WATCHPACK_POLLING` no Next) — editar `apps/api/src` ou `apps/web/{app,components,lib}`
no host já reflete no container rodando. **Exceção**: `node_modules` do `web` é
instalado na *imagem*, não bind-mounted — mudar `package.json` exige
`docker compose build web && docker compose up -d web` para o container pegar.

## Observabilidade

Logs (`structlog`) carregam `request_id` (todo request HTTP, via
`api/middleware.py::CorrelationIdMiddleware`) e `session_id` (sessões de agente, via
`agent/runner.py::stream_run`) — filtrar os dois cobre qualquer investigação. Spans de
execução de ferramenta/busca RAG ficam num buffer em memória (`telemetry/tracer.py`,
`GET /api/telemetry/recent`); custo/latência por chamada de LLM é durável em Postgres
(`router/telemetry.py` → `RequestLog`, `GET /api/metrics/*`); p50/p95 e circuit breaker
por modelo ficam no Redis (`router/health.py`).

## Segurança

Uma única `SICOOBITO_API_KEY` compartilhada (sem contas de usuário) — ver
`api/deps.py::require_api_key`. Sem ela definida, a API aceita qualquer chamada local de
propósito. O gateway do Next (`apps/web/app/api/gateway/[...path]/route.ts`) injeta essa
chave no servidor; o browser nunca a vê. As portas publicadas no `docker-compose.yml` são
`127.0.0.1` apenas — é essa a fronteira de segurança real, não o login da UI. `.env` nunca
é commitado (só `.env.example`); antes de commitar algo que toque credenciais, confirme
que não há segredo em texto puro no diff.

## Convenções de código

- Comentários e docstrings em português; explicam o **porquê**, não o quê — ver o estilo
  em qualquer arquivo de `agent/` ou `router/` como referência.
- Pequena duplicação é preferida a abstração prematura quando os casos são poucos e
  simples de ler direto (ver RAG acima) — não "corrija" isso sem necessidade real.
- Erros de dependência opcional truncam a mensagem (`str(exc)[:200]`) antes de logar —
  evita vazar payload grande ou segredo mal redigido no log.

## Git

- Mensagens de commit em português, formato `tipo(escopo): resumo` (`feat`, `fix`,
  `chore`...), corpo explicando o *porquê* quando não for óbvio.
- Nunca commitar nem dar push sem o usuário pedir explicitamente nesta conversa — mesmo
  que uma vez anterior tenha aprovado, autorização não se generaliza para o próximo commit.
- Sempre criar commit novo, nunca `--amend`, a menos que pedido.
