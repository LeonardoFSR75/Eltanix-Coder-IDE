# ADR 0004 — Orquestração multiagente: falha fechada, sem loop supervisor novo

**Status:** aceito · **Data:** 2026-08-10

## Contexto

Avaliamos o [Strix](https://github.com/usestrix/strix) (pentest autônomo, 50k+
estrelas) em busca de ideias portáveis. O padrão de ferramentas
`create_agent`/`view_agent_graph`/`send_message_to_agent`/`wait_for_agents`/
`agent_finish`/`stop_agent` — um agente pai que spawna filhos especialistas,
troca mensagens com eles e espera pelo resultado — era a peça que faltava nas
melhorias anteriores (a segunda opinião automática já existente é uma chamada
de LLM isolada e bounded, não um agente paralelo de verdade).

O modelo de execução do Strix não se transporta direto: é um processo CLI
único, todos os "agentes" são tasks assíncronas dentro do mesmo processo.
Aqui, `agent/runner.py::AgentRunner.stream_run()` é a ÚNICA coisa que avança o
LangGraph, e hoje só um cliente SSE vivo a consome — não existe execução em
background em lugar nenhum do código antes desta mudança.

## Decisão

**Sem loop supervisor novo.** `stream_run()` já é, por natureza, um burst
limitado: roda até o grafo terminar ou pausar num `interrupt()`, e então
retorna sozinho (checkpoint salvo, lock liberado). `agent/headless.py::
run_headless_burst()` só drena UM desses bursts sem expor via SSE a ninguém —
nada além disso. Um filho que pausa num `interrupt()` fica exatamente como
qualquer sessão pararia: visível em `GET /api/agent/sessions` (agora com
`parent_session_id`), retomável pela MESMA rota `POST /sessions/{id}/run` que
qualquer sessão já usa. Isso significa **o invariante "WRITE/EXEC sempre pausa
para aprovação humana" não muda em nenhum grau** — um burst headless é só um
chamador novo do mesmo portão (`agent/graph.py::approve()`), não um caminho
que o contorna.

**`AgentCoordinator` (`agent/coordinator.py`) falha fechado no `spawn_agent`,
diferente do resto da plataforma.** `router/health.py::HealthTracker` e o
cache degradam pra "mais lento" quando o Redis cai, porque o estado deles é
recuperável a partir da próxima chamada real. Aqui não há fonte de verdade
alternativa pra "quem é filho de quem" e pra caixa de mensagens — rodar sem
coordenação deixaria sessões órfãs que ninguém consegue mensagear, aprovar ou
sequer descobrir que existem. `spawn_agent` recusa nesse caso; os métodos de
leitura/mensagem de um coordenador já existente continuam degradando pra
default seguro (log + retorno vazio), porque falhar todos eles barulhentamente
no meio de uma orquestração em andamento deixaria filhos já rodando sem
conseguir chegar em `agent_finish`.

**`_session_locks` (já existente) é reaproveitado como sinal de "sessão ao
vivo".** Em vez de um marcador novo, `AgentRunner.is_being_driven(session_id)`
consulta o mesmo `asyncio.Lock` por sessão que já existe pra impedir duas
chamadas concorrentes de `stream_run`. `send_message_to_agent` só dispara um
burst novo pra acordar o alvo se ele não estiver sendo dirigido no momento —
senão, quem já está dirigindo drena a caixa de mensagens sozinho.

**`RiskClass` ganha um segundo eixo de julgamento.** Até aqui, READ/WRITE/EXEC
era estritamente sobre efeito em arquivo/shell — `request_code_review` faz uma
chamada real de LLM e é READ porque não toca em nada além disso. `spawn_agent`
é diferente: cria estado durável (worktree, sandbox, checkpoint) e consome
orçamento de forma não aprovada turno-a-turno, então é classificado **WRITE**
mesmo sem tocar em arquivo diretamente — mais perto de `write_file`/
`run_command` em espírito (compromete recursos reais) que de `write_todos`
(estado efêmero em memória). `stop_agent` também é **WRITE**: interrompe
trabalho de outro agente, inclusive ação WRITE/EXEC já aprovada e em
andamento — um efeito real fora do arquivo/shell, tratado com a mesma cautela.
As outras quatro (`view_agent_graph`, `send_message_to_agent`,
`wait_for_agents`, `agent_finish`) seguem READ pelo motivo original: mutam
estado rastreado no coordenador, não arquivo/shell — mesma categoria de
`write_todos`.

**Tetos novos contra fork-bomb**, ausentes até aqui (`router/budget.py::
BudgetGuard` limita USD/dia, nunca quantidade de sessões paralelas):
`Settings.agent_max_children_per_agent` (padrão 4) e
`Settings.agent_max_spawn_depth` (padrão 3 — raiz→filho→neto→bisneto é o
limite), aplicados no handler de `spawn_agent`. `Settings.
agent_wait_max_seconds` (padrão 300) limita o `timeout_seconds` que o modelo
pode pedir em `wait_for_agents`, pra uma chamada de ferramenta não travar o
turno (e a conexão SSE, se for humano dirigindo) por tempo arbitrário.

## Alternativas rejeitadas

- **Loop supervisor contínuo** (um processo/task de longa duração que fica
  reavançando cada agente ativo). Mais parecido com o Strix de verdade, mas
  exigiria um scheduler novo inteiro e duplicaria a lógica de execução que
  `stream_run()` já resolve — burst-por-burst é suficiente porque cada burst
  já roda até não ter mais nada a fazer sozinho.
- **Degradar (não falhar fechado) o `spawn_agent` sem Redis**, rodando o filho
  sem coordenação. Rejeitado: um filho sem coordenador não tem como ser
  mensageado, aparecer em `view_agent_graph`, ou ser parado — pior que recusar
  de cara.
- **`stop_agent` cancelando a task do burst à força.** Cancelamento no meio de
  um `stream_run()` arrisca interromper uma escrita de checkpoint em
  andamento. `stop_agent` (v1) só impede que o alvo seja acordado de novo —
  best-effort, documentado na descrição da ferramenta.

## Consequências

- Sem Redis configurado, orquestração multiagente simplesmente não existe
  (`spawn_agent` recusa) — sessões normais (a grande maioria do uso hoje)
  seguem intocadas.
- Um filho headless que precisa de aprovação humana fica "esperando" sem
  nenhum aviso proativo — descobrir isso hoje depende de alguém abrir
  `GET /api/agent/sessions` e notar `parent_session_id` preenchido com status
  pendente. Uma notificação push fica como trabalho futuro, não coberta aqui.
- `stop_agent` é best-effort — não interrompe um burst já em andamento no meio
  de uma ação, só impede reativação futura. Documentado na própria ferramenta,
  pra o modelo não prometer ao usuário uma parada mais forte do que existe.
