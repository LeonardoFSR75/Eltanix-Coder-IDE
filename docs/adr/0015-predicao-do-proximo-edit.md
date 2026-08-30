# ADR 0015 — Predição do próximo edit ("tab to jump")

**Status:** aceito · **Data:** 2026-08-30

## Contexto

O autocompletar inline (Onda 1.1, [[0014-autocompletar-inline-ghost-text]])
completa no cursor. A Onda 1.2 é o passo seguinte, o recurso que o Cursor
chama de "Tab to jump" e o Copilot de *Next Edit Suggestions*: **depois** de
uma edição, o modelo prevê **onde e o quê** será a próxima edição — quase
sempre propagar a mudança que acabou de ser feita para outro ponto (renomear
um símbolo, ajustar quem chama uma função cuja assinatura mudou, atualizar um
teste). `Tab` pula o cursor até lá; `Tab` de novo aceita o diff.

Isso é diferente da 1.1 em tudo que importa para a arquitetura:

| | 1.1 (autocompletar) | 1.2 (próximo edit) |
|---|---|---|
| Gatilho | cursor parado 250 ms | uma **edição** que assentou (~400 ms) |
| Entrada | prefixo + sufixo no cursor | **histórico de edições recentes** + arquivo atual |
| Saída | texto a inserir no cursor | **um trecho localizado** (linhas X–Y) + substituição |
| Orçamento de latência | p50 < 400 ms | p50 < 1 s (dispara menos) |
| Modelo | rápido, tiny (`completion`) | capaz **e** rápido (`next-edit`) |

Toca os mesmos dois invariantes que a 1.1 (ADR 0001 — porta única de LLM;
config declarativa em YAML), por isso ADR próprio.

## Decisão

### 1. Egress: `RouterEngine.complete()`, saída ancorada em linha

Chamada por `engine.complete(requested_model=<perfil>, params=...,
source="ide:next_edit")`. O modelo recebe o histórico de edições recentes (o
diff do que mudou) + o arquivo atual, e responde **um objeto JSON**:

```json
{"found": true, "start_line": 42, "end_line": 45, "replacement": "..."}
```

ou `{"found": false}`. `start_line`/`end_line` referenciam as linhas do
arquivo **atual**. O servidor valida o intervalo contra o conteúdo recebido
(fora dos limites, ou `old_text` que não bate → descarta), calcula o diff e só
então devolve. Parsing fail-closed: resposta fora do formato → nenhuma
sugestão, nunca exceção (mesmo contrato da 1.1 e de `evals/ragas.py`).
`temperature: 0`, `max_tokens: 256` (um trecho, não um arquivo).

### 2. Perfil de rota novo: `next-edit`

Em `config/routes.yaml`:

```yaml
  # Predição do próximo edit ("tab to jump", Onda 1.2, ADR 0015). Dispara
  # depois de uma edição assentar — menos frequente que o autocompletar, então
  # pode usar um modelo mais capaz; mas ainda precisa responder em ~1 s, então
  # não é o `coding` de 70b puro. `latency` ordena pelo p95 medido.
  next-edit:
    strategy: latency
    models:
      - groq/llama-3.3-70b-versatile
      - databricks/llama-3.3-70b
      - anthropic/claude-haiku-4-5-20251001
      - ollama/qwen2.5-coder:7b
```

Configurável por `IDE_NEXT_EDIT_PROFILE` (default `next-edit`).

### 3. Endpoint novo: `POST /api/context/next-edit`

Em `api/routes/context.py`. `dependencies=[AuthDep]`, RBAC `min_role="viewer"`.
**READ-only** — nunca escreve; a aplicação do edit acontece no cliente no
segundo `Tab`.

- **Request:** `{project, path, file_content, cursor: {line, column},
  recent_edits: [{path, diff}]}`. `file_content` limitado a ~16000 chars (o
  servidor corta em torno do cursor se passar); `recent_edits` a 10 entradas,
  cada `diff` a 2000 chars.
- **Response:** `{found: bool, suggestion_id, edit?: {path, start_line,
  end_line, old_text, new_text, diff}, model, latency_ms}`. **Um** edit, no
  máximo.
- **Cancelamento:** mesmo `await_or_abandon_on_disconnect`
  (`api/_client_disconnect.py`, extraído na 1.1). Uma edição nova antes da
  resposta cancela a chamada em voo.
- **Timeout duro:** 4 s. `found: false` degrada em silêncio, igual à 1.1.

### 4. Escopo do MVP — **mesmo arquivo**

O `edit.path` do MVP é sempre o arquivo aberto — o pulo pode ser para
qualquer linha dele (da 10 para a 340), o que já entrega a maior parte do
valor. **Cross-file fica de fora da 1.2**: exige mandar conteúdo de vários
arquivos, resolver o caminho-alvo com segurança (anti-escape) e abrir o
arquivo no editor no `Tab` — superfície grande, adiada (candidata a 1.2b ou
Onda 3).

### 5. Histórico de edições recentes — no cliente

O `Editor.tsx` já tem o fluxo de mudanças do Monaco
(`onDidChangeModelContent`). A 1.2 mantém um buffer rolante das últimas ~10
mudanças (ou ~60 s), cada uma como um diff compacto, com teto de tamanho. É
**estado só do cliente**, não persiste, não vira sessão no servidor —
mandá-lo no request é mais simples que rastrear edição no backend.

### 6. Interação e o conflito do `Tab`

- Edição assenta → debounce ~400 ms → dispara o request.
- Previu um edit **longe do cursor / fora da tela:** um indicador discreto
  (`Tab ⤵`) perto do cursor. `Tab` #1 rola/move o cursor até o trecho e mostra
  o diff como decoração inline; `Tab` #2 aceita.
- Previu um edit **no/perto do cursor:** vira um diff inline direto, `Tab`
  aceita.
- `Esc` dispensa.

**Precedência do `Tab`** (regra de keybinding com `when`):
`inlineSuggestionVisible` (1.1) vence → senão `nextEditPending` (1.2) →
senão o `Tab` normal (indentar). Um *context key* novo (`eltanixNextEditPending`)
controla isso; sem ele o Monaco indenta como sempre.

Isso é **decoração + keybinding custom** no `Editor.tsx`, separado do
`InlineCompletionsProvider` da 1.1 (o Monaco não tem API nativa de "próximo
edit").

### 7. Telemetria — coluna `kind` em `completion_event`

`next_edit` e `inline` são irmãos: sugestão → `accepted`/`rejected`/`ignored`,
com chars, latência, linguagem, modelo. Em vez de uma tabela paralela,
migração **0030** adiciona `kind` (`'inline'` default | `'next_edit'`) e
`jump_lines` (nullable — distância em linhas do cursor até o trecho previsto,
sinal útil só do next-edit) a `completion_event`.
`POST /api/context/completions/outcome` ganha os dois campos (opcionais);
`GET /api/context/completions/stats` passa a quebrar por `kind`.
Custo/latência de cada chamada já caem em `request_log` com
`source="ide:next_edit"`.

### 8. Kill switch e rate limit

`IDE_NEXT_EDIT_ENABLED` (default `true`; candidato a `false` se a taxa de
aceitação não justificar o custo — é uma chamada mais cara que a 1.1). Rate
limit por ator no Redis, chave própria, `IDE_NEXT_EDIT_MAX_PER_MINUTE`
(default 40 — dispara por edição assentada, bem menos que por tecla). Redis
fora → não limita.

### 9. Frontend

`lib/api/nextEdit.ts` (casca fina sobre `lib/client.ts`, reusa `postOrNull`).
`Editor.tsx`: buffer de edições recentes, chamada com debounce, o indicador
`Tab ⤵`, as decorações do diff previsto e a regra de `Tab`. Desfecho
(`accepted`/`rejected`/`ignored`, com `kind: "next_edit"` e `jump_lines`)
disparado para `/completions/outcome`.

## Escopo — o que 1.2 NÃO é

- **Não** é cross-file (adiado).
- **Não** é uma cadeia de edições ("aceita e prevê a próxima, e a próxima") —
  um edit por vez no MVP; a cadeia é follow-up.
- **Não** é um modelo fine-tuned de diff (o Cursor tem um; nós instruímos um
  modelo de código genérico e aceitamos qualidade menor no MVP).

## Alternativas consideradas

- **Reusar `POST /api/context/completions` com um flag de modo** — rejeitado:
  gatilho, forma da entrada (histórico de edições × prefixo/sufixo), forma da
  saída (trecho localizado × inserção no cursor) e orçamento de latência todos
  diferentes. Rota separada.
- **Cross-file no MVP** — rejeitado: resolução de caminho + contexto
  multi-arquivo + navegação no editor. Superfície grande, adiada.
- **Rastrear histórico de edição no servidor** (sessão com estado) —
  rejeitado: o editor já tem o stream de mudanças; mandar um diff compacto do
  cliente evita estado no backend.
- **Tabela `next_edit_event` separada** — rejeitado: os campos são os mesmos
  de `completion_event`; um discriminador `kind` é mais limpo que uma tabela
  paralela que teria que ser unida na hora de somar.
- **Streaming da resposta** — rejeitado: é um objeto JSON pequeno; streaming
  só complicaria o parse fail-closed e o cancelamento.
- **Perfil `fast` em vez de um `next-edit` dedicado** — rejeitado pelo mesmo
  motivo da 1.1: o operador não conseguiria ajustar só o next-edit sem mexer
  em tudo que usa `fast`, e o next-edit quer uma lista de modelos mais capaz
  que o `completion` mas mais rápida que o `coding`.

## Consequências

- Segundo consumidor de LLM de alta frequência da IDE (depois da 1.1), mais
  caro por chamada — o dashboard de custo vai separar por `source="ide:next_edit"`.
- `Tab` fica com uma cadeia de precedência de três níveis no editor; a regra
  de `when` tem que ser exata ou o `Tab` de indentar "some" às vezes. Coberto
  por teste de componente do `Editor.tsx`.
- `completion_event` deixa de ser "só autocompletar inline" — a migração 0030
  e o `kind` já deixam isso explícito para quem for ler a tabela ou o
  `/stats`.
- Sem um modelo fine-tuned, a qualidade da previsão de next-edit no MVP vai
  ser modesta; o `IDE_NEXT_EDIT_ENABLED=false` existe para desligar sem deploy
  se a taxa de aceitação (agora medida por `kind`) não compensar.
