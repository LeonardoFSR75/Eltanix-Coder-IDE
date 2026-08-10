# Arquitetura — SicoobitoCode

## Visão Geral

```
┌─────────────────────────────────────────────────────────────────┐
│  apps/web — Next.js 15                                          │
│  IDE Monaco · Dashboard · Agent Dock · Second Brain · MCP UI   │
│  Login obrigatório (cookie httpOnly) · Central de Projetos      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP/WS/SSE (cookie de sessão do usuário;
                            │ API key só para ferramenta externa — ADR 0005)
┌───────────────────────────▼─────────────────────────────────────┐
│  apps/api — FastAPI (Python 3.12)                               │
│                                                                 │
│  /v1/*   ← fachada OpenAI-compatible (Cline, Continue, Aider)  │
│  /api/*  ← gestão, métricas, auditoria, IDE, agente            │
│  toda rota: AuthDep = require_session (API key OU sessão — ADR 0005) │
│                                                                 │
│  ┌──── router (ADR 0001: ÚNICA porta de saída para LLM) ──────┐ │
│  │ catalog → policy → engine → adapters                       │ │
│  │              ↑        ↓                                     │ │
│  │           health   pricing → telemetry → request_log        │ │
│  │           (Redis)                                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  auth:      AppUser/AuthSession, scrypt, rate limit (ADR 0005) │
│  optimizer: cache exato + semântico (Redis) · compressor · complexity │
│  context:   chunker (tree-sitter) · indexer · store (pgvector) │
│             + edges.py (Code Knowledge Graph: contains/imports) │
│  agent:     LangGraph (think→approve→act) · tools (RiskClass)  │
│             + coordinator.py (spawn/inbox/wait — ADR 0004)     │
│             + approval_policy.py (auto-aprovação opt-in)       │
│             + review_common.py (segunda opinião consultiva)    │
│  workspace: WorkspaceFS · git (+ blame/co-change) · github · projects │
│  mcp:       MCPManager · conexões stdio/HTTP · confiança por tool │
│  lsp:       ponte WebSocket ↔ language server                  │
│  rag:       documents + notes + context + graphify (4x RAG / GQL CTE expansion) │
│  audit:     registro de aprovações WRITE/EXEC                  │
│  telemetry: TraceRecorder (Redis/memória + Postgres/ToolSpan) + request_log │
│  browser:   sessão do agente (browser_action) + painel manual do IDE │
│                                                                 │
└───┬─────────────┬────────────────────────────────┬─────────────┘
    │             │                                │
┌───▼────┐  ┌────▼────────────────────────┐  ┌───▼──────────────┐
│Postgres│  │  Provedores de LLM          │  │services/executor  │
│pgvector│  │  Ollama · Azure · Databricks│  │(único c/ docker.  │
│Redis   │  │  Anthropic · Groq           │  │sock — ADR 0002)   │
│MinIO   │  └─────────────────────────────┘  └──────────────────┘
└────────┘                                   services/browser
                                             (Chromium isolado
                                              em browser_net)
```

## Fluxo de um Request

1. `POST /v1/chat/completions` chega com `model: "auto/cheap"`.
2. `AuthDep` (`api/deps.py::require_session`) valida API key **ou** cookie de
   sessão — nunca fica aberta por omissão (ADR 0005). `deps.identify_source`
   descobre a ferramenta de origem (header ou User-Agent).
3. `BudgetGuard.check()` avisa — ou bloqueia, se `BUDGET_HARD_STOP` — quando o orçamento estourou.
4. `optimizer.tokens` estima o tamanho do prompt (necessário para custo e para descartar modelos cuja janela não comporta o pedido).
5. `RoutingPolicy.select()` monta a lista ordenada de candidatos, excluindo os sem credencial, com circuito aberto ou janela insuficiente.
6. Para cada candidato, `RouterEngine`:
   - consulta o cache exato e, se habilitado, o cache semântico por
     similaridade de embedding (desligado quando a chamada tem `tools`);
   - chama `litellm.Router.acompletion`;
   - classifica a falha (`FATAL` aborta, `SKIP` pula sem punir, `TRANSIENT` alimenta o breaker) e passa ao próximo.
7. Sucesso: normaliza `usage`, calcula custo, registra saúde, grava o cache e escreve uma linha em `request_log`.

## Decisões que Moldam a Plataforma

**Uma única porta de saída para LLM** (ADR 0001). Nenhum módulo fora de `router/adapters/` importa SDK de provedor. É o que torna Databricks, Foundry, Anthropic, Groq e Ollama plugáveis de verdade e o que garante que nenhuma chamada escape da contabilidade.

**Executor isolado em serviço próprio** (ADR 0002). O serviço `services/executor` é o único com `/var/run/docker.sock` montado. A API interage com ele via HTTP (`EXECUTOR_TOKEN`), impedindo que execuções não autorizadas obtenham privilégios no host.

**LiteLLM como biblioteca, não como proxy.** O `litellm.Router` roda dentro do processo FastAPI com `num_retries=0`. Fallback, retry e ordenação são nossos, porque o litellm não conhece o circuit breaker nem o custo estimado de cada candidato.

**Configuração em YAML, telemetria no banco.** `config/*.yaml` é a única fonte de verdade sobre modelos, rotas, MCP e preços. Não existem tabelas `provider`/`model`: duplicá-las criaria sincronização sem ganho. Os agregados são derivados de `request_log` por consulta.

**Custo desconhecido nunca vira zero.** Um modelo ausente de `pricing.yaml` produz `cost_known=false`, e o dashboard mostra isso como lacuna explícita. O mesmo vale para tokens: contagem local é marcada como `usage_estimated`.

**Degradação em vez de queda.** Redis fora significa perder cache e circuit breaker, não perder o gateway. MinIO fora desabilita RAG de documentos, mantendo o restante funcional.

**Login obrigatório, API key vira canal de serviço** (ADR 0005). Toda rota exige
`require_session`: API key válida (CI, cline, continue, aider, cursor) ou cookie
de sessão de usuário — nunca aberta por omissão. Etapa 1 de um plano em duas
etapas: um único usuário seed, sem RBAC ainda.

**Orquestração multiagente sem loop supervisor novo** (ADR 0004). `spawn_agent`
cria um filho que roda em `stream_run()` — o mesmo burst que já existia —, falha
fechado (recusa) sem Redis configurado, porque não há como mensagear ou descobrir
um filho órfão sem coordenador. `RiskClass` nesse caso é `WRITE` mesmo sem tocar
arquivo: consome orçamento e cria estado durável (worktree, sandbox, checkpoint)
sem aprovação turno-a-turno.

**Aprovação humana continua sendo o portão, mas com dois assistentes
consultivos.** `agent/approval_policy.py` deixa um projeto auto-aprovar
`WRITE`/`EXEC` restrito a regras explícitas em `.sicoobito/approval_policy.yaml`
(glob de caminho + limite de linhas; prefixo de comando com bloqueio de
caracteres perigosos), fail-closed em qualquer ambiguidade. `agent/
review_common.py` roda uma segunda opinião automática antes da aprovação humana
— puramente consultiva, uma falha vira "unavailable", nunca "approved". Nenhum
dos dois substitui `interrupt()` no grafo — só decidem se ele dispara ou não.

**Sincronização de Worktree da Sessão com o Editor Monaco.** As alterações do agente são gravadas isoladamente no seu worktree de sessão (`.sicoobito/worktrees/<session_id>`). O endpoint `GET /api/workspace/file` resolve arquivos cientes do `session_id` ativo com fallback para o workspace principal, permitindo a leitura no editor sem erros de "arquivo não encontrado". O clique em "Aceitar" no `DiffCard` dispara `POST /api/agent/sessions/{session_id}/files/accept`, copiando a alteração para a raiz do workspace do projeto.

**Validação em Malha Fechada (Closed-Loop Execution).** A ferramenta `write_file` executa checagens automáticas de sintaxe AST/JSON no conteúdo gravado, retornando alertas de erro no `ToolResult`. O `SYSTEM_PROMPT` proíbe o encerramento prévio de tarefas de teste ou implementação sem validação e execução bem-sucedida no sandbox.


## Módulos da Aplicação (`apps/api`)

| Módulo | Responsabilidade |
|---|---|
| `auth/` | Login obrigatório do browser: `AppUser`/`AuthSession`, hash `scrypt`, rate limit de login, troca de senha (ADR 0005). |
| `router/` | Gateway de saída LLM: catálogo, políticas de roteamento, adaptadores, custo e contabilidade. |
| `optimizer/` | Cache exato + cache semântico por embedding (Redis), compressão de histórico de contexto e classificação de complexidade do prompt. |
| `context/` | Indexação de código com tree-sitter, embeddings, busca híbrida RRF no pgvector, e Code Knowledge Graph (`edges.py`: arestas `contains`/`imports` entre `code_chunk`). |
| `agent/` | Grafo de execução do agente autônomo (LangGraph), checkpointer Postgres, ferramentas com `RiskClass`, `approval_policy.py` (auto-aprovação opt-in), `review_common.py` (segunda opinião), `coordinator.py` (orquestração multiagente, ADR 0004). |
| `workspace/` | Fronteira do sistema de arquivos (`WorkspaceFS`), integração Git (worktrees, `blame`/`co_change`, identidade por projeto) e GitHub. |
| `sandbox/` | Gerenciamento de containers efêmeros via serviço executor isolado. |
| `mcp/` | Cliente de servidor MCP (stdio/HTTP), catálogo, editor estruturado de `mcp.yaml` e confiança por ferramenta individual (`tool_overrides`). |
| `lsp/` | Ponte de integração entre Monaco Editor no browser e Language Server Protocol por stdio. |
| `documents/` | Ingestão e busca vetorial/híbrida de documentos (PDFs/MDs) via MinIO + pgvector. |
| `notes/` | Segundo Cérebro: gerenciamento de notas interconectadas com `[[wikilinks]]`. |
| `graphify/` | Grafo de Conhecimento e Graph RAG: extração L1 (Wikilinks, Tags, AST/TS Imports), arestas L2/L3, expansão via CTE/GQL, métricas e busca cross-project opt-in. |
| `skills/` | Serviço de armazenamento e execução de habilidades customizadas (Skills). |
| `audit/` | Registro de auditoria durável de ações `WRITE` e `EXEC` aprovadas pelo usuário. |
| `telemetry/` | Buffer `TraceRecorder` (Redis/memória) com persistência durável em Postgres (`ToolSpan`) para spans de ferramentas e RAG. |
| `browser/` | Integração com o serviço de navegação Chromium headless (`services/browser`) — usada pela tool `browser_action` do agente e pelo painel de navegador manual do IDE. |
| `evals/` | Módulo de avaliação continuada de qualidade RAG (métricas hit@k / MRR). |

## Garantias de Segurança

1. **Vínculo Local:** Todas as portas publicadas no `docker-compose.yml` são ligadas exclusivamente a `127.0.0.1`.
2. **Rede Browser Isolada:** O serviço Chromium roda na rede `browser_net` (`internal: true`), impossibilitando acesso à internet pública durante verificação visual.
3. **Fronteira de Arquivos:** `WorkspaceFS` impede navegação com `..` ou caminhos fora de `PROJECTS_ROOT`.
4. **Classificação de Risco:** Ferramentas `WRITE` e `EXEC` exigem aprovação explícita via nó `approve` do LangGraph (`interrupt()`) — auto-aprovação (`approval_policy.py`) só dispensa esse nó dentro de regras explícitas por projeto, fail-closed em ambiguidade.
5. **Login obrigatório (ADR 0005):** `require_session` nunca fica aberta por omissão — API key (canal de serviço) ou cookie de sessão de usuário, sempre uma das duas. Senha em `scrypt`, token de sessão só guardado como hash SHA-256.
