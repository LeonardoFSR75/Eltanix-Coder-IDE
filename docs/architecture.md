# Arquitetura

## Visão geral

```
┌────────────────────────────────────────────────────────────────┐
│  apps/web — Next.js 15                                         │
│  Dashboard de custo · Provedores · Requests                    │
│  (fases futuras: editor Monaco, chat, terminal)                 │
└───────────────────────────┬────────────────────────────────────┘
                            │ HTTP (chave da API só no servidor Next)
┌───────────────────────────▼────────────────────────────────────┐
│  apps/api — FastAPI (Python 3.12)                              │
│                                                                 │
│  /v1/*     fachada OpenAI-compatible ← Cline, Continue, Aider,  │
│                                          Claude Code, curl      │
│  /api/*    saúde, catálogo, métricas                            │
│                                                                 │
│  ┌───────────────── router (única saída para LLM) ───────────┐  │
│  │ catalog → policy → engine → adapters                      │  │
│  │              ↑        ↓                                    │  │
│  │           health   pricing → telemetry → request_log       │  │
│  │           (Redis)                                          │  │
│  └────────────────────────────────────────────────────────────┘  │
│  optimizer: cache exato (Redis) · estimativa de token          │
└───────┬──────────────────────────────────────┬─────────────────┘
        │                                      │
  ┌─────▼──────┐                        ┌──────▼──────┐
  │ PostgreSQL │                        │  Provedores │
  │ + pgvector │                        │  ollama     │
  │            │                        │  azure      │
  │  Redis     │                        │  databricks │
  └────────────┘                        └─────────────┘
```

## Fluxo de um request

1. `POST /v1/chat/completions` chega com `model: "auto/cheap"`.
2. `deps.identify_source` descobre a ferramenta de origem (header ou User-Agent).
3. `BudgetGuard.check()` avisa — ou bloqueia, se `BUDGET_HARD_STOP` — quando o
   orçamento estourou.
4. `optimizer.tokens` estima o tamanho do prompt (necessário para custo e para
   descartar modelos cuja janela não comporta o pedido).
5. `RoutingPolicy.select()` monta a lista ordenada de candidatos, excluindo os
   sem credencial, com circuito aberto ou janela insuficiente.
6. Para cada candidato, `RouterEngine`:
   - consulta o cache exato (acerto → devolve sem gastar token);
   - chama `litellm.Router.acompletion`;
   - classifica a falha (`FATAL` aborta, `SKIP` pula sem punir, `TRANSIENT`
     alimenta o breaker) e passa ao próximo.
7. Sucesso: normaliza `usage`, calcula custo, registra saúde, grava o cache e
   escreve uma linha em `request_log`.

## Decisões que moldam o resto

**Uma única porta de saída para LLM** (ADR 0001). Nenhum módulo fora de
`router/adapters/` importa SDK de provedor. É o que torna Databricks e Foundry
plugáveis de verdade e o que garante que nenhuma chamada escape da contabilidade.

**LiteLLM como biblioteca, não como proxy.** O `litellm.Router` roda dentro do
processo FastAPI com `num_retries=0`. Fallback, retry e ordenação são nossos,
porque o litellm não conhece o circuit breaker nem o custo estimado de cada
candidato.

**Configuração em YAML, telemetria no banco.** `config/*.yaml` é a única fonte de
verdade sobre modelos, rotas e preços. Não existem tabelas `provider`/`model`:
duplicá-las criaria sincronização sem ganho. Também não existe `usage_daily` —
os agregados são derivados de `request_log` por consulta, e agregado derivado
nunca fica defasado do fato.

**Custo desconhecido nunca vira zero.** Um modelo ausente de `pricing.yaml`
produz `cost_known=false`, e o dashboard mostra isso como lacuna explícita. O
mesmo vale para tokens: contagem local é marcada como `usage_estimated`.

**Degradação em vez de queda.** Redis fora significa perder cache e circuit
breaker, não perder o gateway. Falha de escrita de telemetria não invalida uma
resposta já paga.

## Módulos

| Caminho | Responsabilidade |
|---|---|
| `router/catalog.py` | Carrega e valida `providers.yaml` / `routes.yaml` |
| `router/adapters/` | Traduz cada provedor para parâmetros do litellm |
| `router/policy.py` | Ordena candidatos (priority, cost, latency, score) |
| `router/health.py` | Circuit breaker e latência p50/p95, estado no Redis |
| `router/pricing.py` | Normaliza `usage` entre provedores e calcula custo |
| `router/engine.py` | Executa, faz fallback, grava cache e telemetria |
| `router/budget.py` | Gasto do dia/mês derivado de `request_log` |
| `optimizer/cache.py` | Cache exato de respostas determinísticas |
| `optimizer/tokens.py` | Estimativa local de tokens |
| `api/v1/` | Fachada OpenAI-compatible |
| `api/routes/` | Saúde, catálogo, métricas |

## O que ainda não existe

As fases 2 a 5 do plano — indexação do repositório com tree-sitter e pgvector,
agente LangGraph, sandbox Docker, integração Git/GitHub e o editor Monaco. Os
diretórios `context/`, `agent/`, `workspace/` e `sandbox/` estão reservados, e a
extensão `vector` já é criada na migração inicial para que a fase 2 não exija
mudança de infra.
