# ADR 0014 — Autocompletar inline (ghost text) no editor

**Status:** aceito · **Data:** 2026-08-30

## Contexto

A maior lacuna da IDE contra Cursor/Copilot é o autocompletar inline: o cursor
para, e em ~300 ms aparece uma sugestão cinza (1–8 linhas) que se aceita com
`Tab`. Hoje a IDE só tem o Cmd+K (`POST /api/agent/inline-edit`, Fase 7), que
exige seleção + instrução escrita — é edição sob demanda, não completar
enquanto digita.

Isso é a Onda 1.1 do roadmap de melhorias de ponta a ponta
([[project-ponta-a-ponta-roadmap]]). Toca dois invariantes do `CLAUDE.md` raiz e
por isso precisa de ADR:

1. **ADR 0001 — porta única de saída para LLM.** O autocompletar chama modelo a
   cada pausa de digitação: é o consumidor de LLM mais frequente do produto. Não
   pode abrir um caminho próprio para provedor nem depender de um endpoint FIM
   dedicado.
2. **Config declarativa em YAML.** Qual modelo responde o autocompletar é uma
   escolha de custo/latência que o operador tem que poder ajustar sem recompilar
   — tem que morar em `routes.yaml`, não numa constante Python.

Nenhum modelo do `providers.yaml` anuncia capacidade `fim`/`infill` nativa —
todos são `chat`. Então "completar no cursor" é feito por **prompting FIM sobre
chat**: system prompt cirúrgico + mensagem com `prefixo` (até o cursor) e
`sufixo` (depois do cursor), devolvendo só o texto a inserir. É o mesmo formato
que o `inline-edit` já usa para editar um trecho.

## Decisão

### 1. Egress: `RouterEngine.complete()`, sem exceção

O autocompletar chama `engine.complete(requested_model=<perfil>, params=...,
source="ide:completion")`. Nenhum SDK de FIM, nenhuma rota nova de provedor. A
contabilidade de token/custo, o cache exato, o circuit breaker e a sanitização
de PII (ADR 0011) vêm de graça porque a chamada passa pelo mesmo motor de
sempre. `temperature: 0`, `max_tokens: 64` (teto duro — ghost text longo demais
atrapalha), `stop` nas quebras que encerram a inserção.

### 2. Perfil de rota novo: `completion`

Em `config/routes.yaml`:

```yaml
  # Autocompletar inline (ghost text). Dispara a cada pausa de digitação, então
  # o que importa é latência de teclado, não capacidade: um modelo de código de
  # 70b a 2–4 s é inutilizável aqui. `latency` ordena pelo p95 medido; a lista
  # é o desempate e o fallback quando o circuito abre.
  completion:
    strategy: latency
    models:
      - ollama/qwen2.5-coder:1.5b      # local, custo zero, treinado p/ FIM
      - groq/llama-3.1-8b-instant      # nuvem ultrarrápida, fallback
      - ollama/qwen2.5-coder:7b
```

Configurável por `IDE_COMPLETION_PROFILE` (default `completion`) — trocar para
`fast` ou um id concreto é um ajuste de `.env`, não de código.

### 3. Endpoint novo: `POST /api/context/completions`

Mora em `api/routes/context.py` (autocompletar é assunto de contexto/editor,
uma rota por domínio). `dependencies=[AuthDep]`, RBAC `min_role="viewer"`.

- **Request:** `{project, path, prefix, suffix, language, max_prefix_chars?,
  max_suffix_chars?}`. `prefix` limitado a 4000 chars, `sufixo` a 2000 (teto de
  custo; o servidor trunca pela borda mais próxima do cursor).
- **Response:** `{completion: str, suggestion_id: str, model: str, cached: bool,
  latency_ms: int}`.
- **READ-only.** Nunca escreve arquivo — não passa por `ApprovalPolicy`
  (diferente do `inline-edit`). Não há o que aprovar: a inserção só acontece no
  cliente quando o humano aperta `Tab`.
- **Cancelamento:** reaproveita o `_await_or_abandon_on_disconnect` de
  `agent.py` (extraído para `api/_client_disconnect.py` como helper
  compartilhado). O cliente aborta a request quando o usuário digita de novo →
  o servidor cancela o `engine.complete()` → nenhum token é gasto por sugestão
  descartada.

### 4. Orçamento de latência

| Métrica | Alvo |
|---|---|
| p50 ponta a ponta (modelo local) | < 400 ms |
| p95 ponta a ponta | < 900 ms |
| Timeout duro do servidor | 2 s (além disso a sugestão já nasceu velha) |
| Debounce do cliente | 250 ms após a última tecla |

Uma tecla nova cancela a request em voo antes de disparar a próxima.

### 5. Cache — nenhuma camada nova no servidor

1. O `ResponseCache` exato do `RouterEngine` já cobre prefixo/sufixo idênticos.
2. No cliente: guarda a última sugestão devolvida com a posição do cursor. Se o
   usuário digita exatamente os primeiros chars dela, o cliente encurta a
   sugestão localmente, sem round-trip (o truque de prefix-match do Copilot).

### 6. Rate limit

Mesmo `INCR`+`expire` por ator do `_guard_inline_edit_rate`, teto mais alto
(`IDE_COMPLETION_MAX_PER_MINUTE`, default 120) porque ghost text dispara muito
mais que Cmd+K. Redis fora → não limita (degrada, não derruba).

### 7. Telemetria desde o dia 1

- **Custo/latência:** toda chamada já cai em `request_log` via
  `router/telemetry.py` com `source="ide:completion"` — latência, TTFT, tokens,
  modelo, nº de fallbacks, sem código novo.
- **Aceitação (novo):** `POST /api/context/completions/outcome`
  `{suggestion_id, outcome: "accepted"|"rejected"|"ignored", shown_ms,
  chars_suggested, chars_accepted}`, best-effort (fire-and-forget do cliente).
  Grava numa tabela nova `completion_event` (migração 0029) — é analítica
  durável, não span em memória (`TraceRecorder`) nem custo de LLM
  (`request_log`). **Não** guarda prefixo/sufixo: só contagem de chars,
  linguagem, modelo, desfecho.
- **Agregado:** `GET /api/context/completions/stats?days=` deriva de
  `completion_event` a taxa de aceitação (por evento e por char), latência
  média e a quebra por linguagem — mesmo estilo do `api/routes/metrics.py`
  (SQL sobre a tabela de fatos, sem agregado materializado). Não há stack
  Prometheus no projeto; se entrar (Onda 3.6), este endpoint vira a fonte do
  exporter.

### 8. Kill switch

`IDE_INLINE_COMPLETIONS_ENABLED` (default `true`). Desligado: o endpoint
responde `204` e o provider do Monaco não registra nada. Erro de modelo →
completion vazia, **nunca** um toast de erro — falha de ghost text é silenciosa.

### 9. Frontend

`apps/web/lib/api/completions.ts` (casca fina sobre `lib/client.ts`, a regra do
cliente HTTP único). `Editor.tsx` registra
`monaco.languages.registerInlineCompletionsProvider` para a linguagem ativa,
ligado a uma chamada com debounce de 250 ms. `Tab` aceita (nativo do Monaco
para inline completions). O desfecho (`accepted`/`rejected`/`ignored`) é
disparado ao aceitar, ao descartar, ou após 3 s de sugestão exibida sem ação.

## Escopo — o que 1.1 NÃO é

- **Não** é predição do próximo local de edição ("tab to jump") — isso é a
  Onda 1.2, ADR próprio.
- **Não** é geração de função inteira sob demanda — isso é Cmd+K / Onda 1.3.
- 1.1 é: cursor parado 250 ms → uma sugestão inline (1–8 linhas) → `Tab` ou
  continua digitando.

## Alternativas consideradas

- **Endpoint FIM dedicado (Ollama `/api/generate` com `suffix`)** — pularia o
  prompting sobre chat e daria FIM "de verdade". Rejeitado: fura o ADR 0001
  (segundo caminho para provedor, sem contabilidade central) e amarra o
  autocompletar ao Ollama, quebrando o fallback para Groq quando o local está
  fora.
- **Reusar o perfil `fast`** — já existe. Rejeitado: inclui
  `databricks/llama-3.3-70b` e `claude-haiku`, caros/pesados demais para
  disparar a cada tecla; o operador não conseguiria ajustar só o autocompletar
  sem afetar todo o resto que usa `fast`.
- **Streaming da completion** — TTFT menor na teoria. Rejeitado para a 1.1: com
  `max_tokens: 64` a resposta inteira chega em um chunk na prática, e o
  streaming complica o cancelamento e o cache exato. Reavaliar se a 1.2 pedir
  multi-linha longa.
- **Sem tabela `completion_event`, telemetria só via `request_log`** — menos
  uma migração. Rejeitado: `request_log` não tem onde pendurar o desfecho
  (aceito/rejeitado) nem os chars aceitos, que são o número que importa para
  saber se o autocompletar presta.

## Consequências

- Um novo consumidor de LLM de altíssima frequência entra no `request_log` — o
  dashboard de custo vai mostrar `ide:completion` provavelmente como a maior
  linha por volume de chamadas (mas baixa por token, com `max_tokens: 64` e
  modelo local à frente).
- `routes.yaml` ganha um perfil que **precisa** de um modelo de baixa latência
  disponível para o recurso valer a pena; sem Ollama local nem Groq, o
  autocompletar cai no fallback lento e o orçamento de latência estoura — aí o
  kill switch existe para desligar sem deploy.
- Extrair `_await_or_abandon_on_disconnect` para um helper compartilhado mexe em
  `agent.py` (troca import) — mudança mecânica, coberta pelos testes de
  `inline-edit` que já existem.
