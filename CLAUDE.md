# SicoobitoCode

IDE agêntica local-first: FastAPI (`apps/api`) + Next.js (`apps/web`) + Svelte 5/Tauri (`apps/desktop`), Postgres+pgvector,
Redis, MinIO, tudo via Docker Compose. Ver [README.md](README.md) para a visão de produto
e como subir a stack — este arquivo é sobre como trabalhar no código.

Guias específicos: [apps/api/CLAUDE.md](apps/api/CLAUDE.md), [apps/web/CLAUDE.md](apps/web/CLAUDE.md), [apps/desktop/CLAUDE.md](apps/desktop/CLAUDE.md).

---

## 🧠 Protocolo de Consulta Obrigatória para Agentes de IA (Obsidian & Graphify)

> [!IMPORTANT]
> **REGRA FUNDAMENTAL PARA AGENTES (Claude, Gemini, Antigravity, Subagentes e Modelos Locais):**
> É **OBRIGATÓRIO** consultar a base de conhecimento do **Segundo Cérebro & Knowledge Graph** no Obsidian (`graphify-out/obsidian/`) e os ADRs antes de propor ou executar alterações arquiteturais, refatorações amplas, novos módulos ou modificações em segurança/roteamento.

### 📚 Fontes Obrigatórias de Consulta:
1. **Painel Central & MOCs do Obsidian (`graphify-out/obsidian/00 - 🏠 Painel & MOCs/`)**:
   - `00 - 🏠 Início (MOC Principal).md`: Dashboard mestre com visão 360°, tabela de decisões e top hubs.
   - `MOC - Arquitetura & Sistema.md` e MOCs temáticos especializados.
   - `Mapa Arquitetural SicoobitoCode.canvas`: Fluxo visual interativo dos componentes.
2. **Registro de Decisões Arquiteturais (`docs/adr/` e `01 - 📑 Documentos & ADRs/`)**:
   - `ADR 0001 — Camada Única de LLM`
   - `ADR 0002 — Executor Isolado`
   - `ADR 0003 — Grafo de Conhecimento e Graph RAG (Graphify)`
   - `ADR 0004 — Orquestração Multiagente`
   - `ADR 0005 — Login Obrigatório com Sessão por Cookie`
   - `ADR 0006 — Integração Firecrawl para Web Scraping, Search e Ingestão de Docs no RAG`
3. **Histórico de Fases & Roadmap (`01 - 📑 Documentos & ADRs/Notas de Projeto (Roadmap & Fases)/`)**:
   - 20 notas sequenciais (`00-MOC.md` a `19-robustez-agente-router-orquestracao-multiagente.md`).
4. **Ferramenta `graph_search` (em tempo de execução)**:
   - Em sessões agênticas, consultar o grafo de conhecimento via ferramenta `graph_search` para mapear dependências em $N$-hops e avaliar impacto de alterações antes de gravar arquivos.

---

## Invariantes de arquitetura (não violar sem atualizar o ADR correspondente)

- **Uso Obrigatório do Grafo e Segundo Cérebro** (`docs/adr/0003-grafo-de-conhecimento-graphify.md`):
  Todo agente deve respeitar a malha relacional do repositório. Decisões arquiteturais devem ser
  registradas em ADR e refletidas no vault Obsidian (`graphify-out/obsidian/`).
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
- **Login é obrigatório para o browser** (`docs/adr/0005-login-obrigatorio.md`): toda rota
  usa `AuthDep = Depends(require_session)` (`api/deps.py`) — aceita `SICOOBITO_API_KEY`
  válida (canal de serviço para CI/cline/cursor/aider) OU cookie de sessão válido, e nunca
  fica aberta por omissão. `require_api_key` ainda existe no código mas não é mais o guard
  de rota nenhuma — não reintroduzir esse padrão em rota nova.

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

Duas credenciais, dois propósitos (`docs/adr/0005-login-obrigatorio.md`):
`SICOOBITO_API_KEY` é o canal de serviço para ferramenta externa (CI, cline, continue,
aider, cursor) — o gateway do Next (`apps/web/app/api/gateway/[...path]/route.ts`) **não**
a reencaminha para chamadas do browser do usuário. Login de usuário (`AppUser` +
`AuthSession` em `db/models.py`, `auth/service.py`) é obrigatório para o browser: senha em
`scrypt`, sessão por cookie `httpOnly` (só o hash SHA-256 do token persiste). Etapa 1 de um
plano em duas etapas — um único usuário seed (`SICOOBITO_ADMIN_USERNAME`/
`SICOOBITO_ADMIN_PASSWORD`, ver `main.py::lifespan`), sem RBAC ainda. As portas publicadas
no `docker-compose.yml` seguem `127.0.0.1` apenas — continua sendo uma camada de defesa,
não a única. `.env` nunca é commitado (só `.env.example`); antes de commitar algo que
toque credenciais, confirme que não há segredo em texto puro no diff.

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
