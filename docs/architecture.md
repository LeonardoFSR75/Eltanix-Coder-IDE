# Arquitetura — SicoobitoCode

## Visão Geral

```
┌─────────────────────────────────────────────────────────────────┐
│  apps/web — Next.js 15                                          │
│  IDE Monaco · Dashboard · Agent Dock · Second Brain · MCP UI   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP/WS (API key injetada no servidor)
┌───────────────────────────▼─────────────────────────────────────┐
│  apps/api — FastAPI (Python 3.12)                               │
│                                                                 │
│  /v1/*   ← fachada OpenAI-compatible (Cline, Continue, Aider)  │
│  /api/*  ← gestão, métricas, auditoria, IDE, agente            │
│                                                                 │
│  ┌──── router (ADR 0001: ÚNICA porta de saída para LLM) ──────┐ │
│  │ catalog → policy → engine → adapters                       │ │
│  │              ↑        ↓                                     │ │
│  │           health   pricing → telemetry → request_log        │ │
│  │           (Redis)                                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  optimizer: cache (Redis) · compressor · complexity · tokens   │
│  context:   chunker (tree-sitter) · indexer · store (pgvector) │
│  agent:     LangGraph (think→approve→act) · tools (RiskClass)  │
│  workspace: WorkspaceFS · git · github · projects              │
│  mcp:       MCPManager · conexões stdio/HTTP                   │
│  lsp:       ponte WebSocket ↔ language server                  │
│  rag:       documents + notes + context (3x hybrid_search RRF) │
│  audit:     registro de aprovações WRITE/EXEC                  │
│  telemetry: TraceRecorder (Redis/memória) + request_log (Postgres)│
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
2. `deps.identify_source` descobre a ferramenta de origem (header ou User-Agent).
3. `BudgetGuard.check()` avisa — ou bloqueia, se `BUDGET_HARD_STOP` — quando o orçamento estourou.
4. `optimizer.tokens` estima o tamanho do prompt (necessário para custo e para descartar modelos cuja janela não comporta o pedido).
5. `RoutingPolicy.select()` monta a lista ordenada de candidatos, excluindo os sem credencial, com circuito aberto ou janela insuficiente.
6. Para cada candidato, `RouterEngine`:
   - consulta o cache exato (acerto → devolve sem gastar token);
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

## Módulos da Aplicação (`apps/api`)

| Módulo | Responsabilidade |
|---|---|
| `router/` | Gateway de saída LLM: catálogo, políticas de roteamento, adaptadores, custo e contabilidade. |
| `optimizer/` | Cache exato (Redis), compressão de histórico de contexto e classificação de complexidade do prompt. |
| `context/` | Indexação de código com tree-sitter, embeddings e busca híbrida RRF no pgvector. |
| `agent/` | Grafo de execução do agente autônomo (LangGraph), checkpointer Postgres e ferramentas com `RiskClass`. |
| `workspace/` | Fronteira do sistema de arquivos (`WorkspaceFS`), integração Git (worktrees) e GitHub. |
| `sandbox/` | Gerenciamento de containers efêmeros via serviço executor isolado. |
| `mcp/` | Cliente de servidor MCP (stdio/HTTP), catálogo e editor estruturado de `mcp.yaml`. |
| `lsp/` | Ponte de integração entre Monaco Editor no browser e Language Server Protocol por stdio. |
| `documents/` | Ingestão e busca vetorial/híbrida de documentos (PDFs/MDs) via MinIO + pgvector. |
| `notes/` | Segundo Cérebro: gerenciamento de notas interconectadas com `[[wikilinks]]`. |
| `skills/` | Serviço de armazenamento e execução de habilidades customizadas (Skills). |
| `audit/` | Registro de auditoria durável de ações `WRITE` e `EXEC` aprovadas pelo usuário. |
| `telemetry/` | Buffer `TraceRecorder` com suporte a persistência no Redis para spans de ferramentas e RAG. |
| `browser/` | Integração com o serviço de navegação Chromium headless (`services/browser`). |
| `evals/` | Módulo de avaliação continuada de qualidade RAG (métricas hit@k / MRR). |

## Garantias de Segurança

1. **Vínculo Local:** Todas as portas publicadas no `docker-compose.yml` são ligadas exclusivamente a `127.0.0.1`.
2. **Rede Browser Isolada:** O serviço Chromium roda na rede `browser_net` (`internal: true`), impossibilitando acesso à internet pública durante verificação visual.
3. **Fronteira de Arquivos:** `WorkspaceFS` impede navegação com `..` ou caminhos fora de `PROJECTS_ROOT`.
4. **Classificação de Risco:** Ferramentas `WRITE` e `EXEC` exigem aprovação explícita via nó `approve` do LangGraph (`interrupt()`).
