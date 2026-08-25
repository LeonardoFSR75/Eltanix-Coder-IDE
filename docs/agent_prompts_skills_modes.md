# Agente: Prompts, Modos e Skills — Mapeamento Completo

Documento de referência do funcionamento real (não aspiracional) do agente de codificação:
como o system prompt é montado, como os 7 modos de execução mudam o comportamento, como o
sistema de skills funciona hoje, e como a aprovação humana se encaixa nisso tudo. Serve de base
factual para qualquer proposta de upgrade — todo trecho abaixo tem correspondência direta em
código, citada por arquivo.

## 1. O ciclo do agente (`agent/graph.py`)

LangGraph com três nós, sempre neste ciclo:

```
think ──(sem tool_calls)──► END
  │
  ├─(tool_calls sem risco)──► act ──► think
  │
  └─(tool_calls com risco WRITE/EXEC)──► approve ──► act ──► think
```

- **`think`**: monta `[{"role": "system", "content": system_prompt}, *mensagens]`, chama
  `engine.complete()` (a única porta de saída para LLM, ver ADR 0001) com `tools=_tool_schemas(mode, has_plan)`
  e `temperature=0`. Se a resposta não pede nenhuma ferramenta, a sessão termina (`finished=True`).
- **`approve`**: para cada tool-call de risco `WRITE`/`EXEC`, primeiro tenta a `ApprovalPolicy`
  do projeto (regras opt-in, fail-closed — ver seção 5); o que sobra vira um `interrupt()` do
  LangGraph, que salva o estado no checkpointer e devolve controle à API — a sessão fica pausada
  até uma decisão humana chegar via `POST /api/agent/sessions/{id}/approve`.
- **`act`**: executa cada tool-call aprovada, monta `role: tool` messages com `content` (texto pro
  modelo) e `data` (estruturado, pra UI renderizar cards — ver `agent/cards/`). Tem um detector de
  repetição (`REPETITION_THRESHOLD = 3`): a mesma chamada com os mesmos argumentos falhando 3x
  seguidas é bloqueada com uma mensagem de erro em vez de rodar de novo.

Teto de iterações: `DEFAULT_MAX_ITERATIONS = 25` (`agent/graph.py:44`). Ao atingir, a sessão
termina com uma mensagem padrão pedindo revisão humana — não é silencioso.

## 2. System prompt (`agent/prompts.py`)

**Um único bloco estático** (`SYSTEM_PROMPT`, ~200 linhas, todo em português), igual para
**todos os 7 modos e toda tarefa**, dividido em 8 seções fixas:

1. Uso prioritário de extensões/frameworks visuais (Tailwind, Shadcn, Lucide, Alpine/HTMX, Chart.js,
   Firecrawl, pgvector, Redis, Semgrep/Bandit, FastAPI-only, Playwright, Graphify)
2. Protocolo de planejamento de 5 fases (domínio/edge-cases → schemas/contratos → componentes UI
   → testes → execução via `write_todos`)
3. Guia de design system (paleta, tipografia, espaçamento, glassmorphism, componentes, proibições)
4. Engenharia de produção (zero stubs, clean architecture em camadas, RFC 7807)
5. Segurança defensiva (SQLi/XSS/path traversal, anti-SSRF, sandbox sem rede direta)
6. Protocolo de testes + validação visual no navegador interno
7. Base de conhecimento (`code_graph`, `search_notes`/`save_note`, `list_skills`/`load_skill`/`propose_skill`, Firecrawl)
8. Estilo de comunicação (português, direto, técnico)

Composição em `agent/graph.py::build_graph()` (linha 214-228): `SYSTEM_PROMPT` +
`\n\n## Instruções do projeto\n\n{custom_instructions}` (se `.novaai_studio/instructions.md`
existir) + `\n\n## Especialização deste agente\n\n{specialization_prompt}` (só para agentes
filhos spawnados pelo coordenador multiagente, ADR 0004). Calculado **uma vez por sessão**, não
por turno — de propósito, para preservar o prefixo estável e aproveitar cache de prompt do
provedor.

**Implicação prática**: uma tarefa de "mudar a cor de um botão" recebe o mesmo tratado de 200
linhas sobre metodologia de 5 fases, RFC 7807 e SSRF que uma tarefa de "criar um novo módulo de
faturamento". Não há segmentação por tamanho/tipo de tarefa.

### 2.1 Prompt por tarefa (`build_task_prompt()`, `prompts.py:213`)

Além do system prompt fixo, cada tarefa nova monta uma mensagem inicial com:
- Mapa do repositório (se fornecido)
- Fluxo obrigatório de início (5 passos fixos: `list_files` → `manage_packages(list)` →
  `search_code`/`read_file` → skills visuais → `write_todos`)
- Arquivos/pasta em foco (`focus_files`/`focus_folder`, vindos dos chips da UI — ver seção 6)
- Bloco específico do modo (seção 3)
- A tarefa em si

## 3. Os 7 modos (`agent/prompts.py::build_task_prompt`, `agent/graph.py::_tool_schemas`)

Cada modo é **hardcoded em Python** — não existe modo customizável pelo usuário. Dois mecanismos
independentes controlam o comportamento por modo:

### 3.1 Gate de ferramentas (`_tool_schemas`, `graph.py:161`)

| Modo | Ferramentas disponíveis |
| --- | --- |
| `ask`, `explore` | Só leitura (`allow_exec=False, allow_write=False`) |
| `edit` | Leitura + escrita, sem exec (`allow_exec=False, allow_write=True`) |
| `plan`, `orchestra` **sem plano ainda** | Só leitura — igual a `ask` (nenhuma ferramenta de escrita liberada até `write_todos` ser chamado) |
| `plan`, `orchestra` **com plano** | Tudo (`registry.schemas()` completo) |
| `agent`, `auto` | Tudo, sempre |

O gate por `has_plan` é reforçado no **schema**, não só na instrução do prompt — é o motivo pelo
qual "Modo Planejar" de fato bloqueia edição antes do primeiro `write_todos`, em vez de depender
do modelo obedecer texto.

### 3.2 Bloco de instrução por modo (`build_task_prompt`, `prompts.py:248-297`)

- **`plan`**: ferramentas de escrita bloqueadas até `write_todos`; depois disso, cria/atualiza
  arquivos livremente. Não é "planejar e parar" — o "Modo Planejar" desta IDE termina executando,
  só adia o início.
- **`auto`**: execução ponta a ponta, sem pausas conceituais adicionais (a aprovação humana via
  `interrupt()` continua valendo para ações `WRITE`/`EXEC`, isso é ortogonal ao modo).
- **`orchestra`**: ciclo TDD estrito por item do plano — teste falha → implementa → teste passa →
  `request_code_review` → só com `APPROVED` chama `git_commit` e marca `completed`. É o único modo
  que amarra commit a aprovação de revisão automática.
- **`edit`**: cirurgia pontual, sem exigir plano prévio.
- **`ask`**: só resposta técnica, sem tocar em nada.
- **`explore`**: como `ask`, mas focado em arquitetura (`code_graph`, `code_history`,
  `find_circular_imports`, `find_orphan_modules`) — toda afirmação precisa citar a ferramenta e o
  resultado que a sustenta.
- **`agent`**: modo padrão implícito — sem bloco de instrução dedicado em `build_task_prompt`
  (nenhum `elif mode == "agent"` existe), cai direto no fluxo obrigatório de início + tarefa. É o
  modo "interativo, edita e roda testes pedindo aprovação" (`MODE_HINT.agent`).

Fonte única do texto de cada modo no frontend: `apps/web/components/ide/agent/modes.ts` — usado
tanto pelo indicador no input do chat quanto pela aba "Agentes" do popover de Personalizações,
para os dois nunca divergirem.

## 4. Skills — três camadas distintas, não confundir

### 4.1 Skills do agente (banco de dados, `novaai_studio.skills.*`)

O que `list_skills`/`get_skill`/`propose_skill` (`agent/tools/skills.py`) realmente leem é a
tabela `skill` do Postgres, **não** arquivos lidos em tempo real. Seedada uma vez no `lifespan`
(`main.py:167`, `seed_agent_skills(Path(".agents"))`) via `rglob("SKILL.md")` recursivo em
`.agents/` — isso pega **dois conjuntos de arquivos ao mesmo tempo**:

- `.agents/skills/master-*/SKILL.md` + subpastas (12 arquivos) — a taxonomia curada do projeto
  (master-dev, master-security, master-ai, master-creativity + especializadas), documentada em
  [`docs/skills_hub.md`](skills_hub.md).
- `.agents/agent-skills/skills/*/SKILL.md` (~25 arquivos) — o kit vendorizado de Addy Osmani
  (TDD, spec-driven-development, code-review, frontend-ui-engineering, security-and-hardening,
  etc. — ver `.agents/agent-skills/README.md`), trazido como está.

Total: **~37 "skills"** na tabela, todas com o mesmo shape (`name`, `description`, `category`,
`system_prompt` = corpo do `.md`, `parameters_json`). O seed só insere skills com `name` ainda
não existente — não atualiza uma skill já seedada se o `.md` de origem mudar (sem re-seed
automático).

**Ponto crítico de descoberta**: nada injeta essas skills no contexto automaticamente. O agente
só as vê se ele mesmo chamar `list_skills` — e o único empurrão para isso no `SYSTEM_PROMPT` é
uma linha na seção 1.2 ("antes de estruturar a UI... chame `list_skills`"), específica de UI/frontend,
não universal. Não há roteamento por similaridade de descrição↔tarefa (diferente do mecanismo
nativo de Skills do Claude Code, onde o modelo recebe a lista de skills disponíveis com suas
descrições já no prompt e decide ativamente qual usar).

`propose_skill` é a via de "Self-Improving Skill": o agente pode gravar uma skill nova no banco
e, se `workspace_root` existir, também em `.novaai_studio/skills/<slug>.md` — mas esse arquivo de
projeto **não é relido em nenhum lugar** (não há `rglob` sobre `.novaai_studio/skills/` em nenhum
arquivo do repositório) — funciona só como registro em Git, não como fonte viva.

### 4.2 UI de skills (`CustomizationsPopover.tsx`, `/skills`)

A aba "Habilidades" do popover (`categoria === "skills"`) lista as skills via `GET` (endpoint
`lib/api/skills.ts`) e permite `toggle` (ativar/desativar) — `list_skills` no backend já filtra
`only_enabled=True`, então desativar aqui de fato remove a skill do que o agente pode descobrir.
Não há edição de conteúdo nem criação manual no popover — isso fica em `/skills` (página dedicada,
não auditada neste documento).

### 4.3 Skills do Claude Code (`.claude/skills/`) — sistema paralelo, não relacionado

`.claude/skills/graphify/SKILL.md` é do **Claude Code** (o CLI usado nesta sessão), carregado
pelo mecanismo nativo `Skill` tool do próprio Claude Code — não tem nenhuma relação com o sistema
de skills do agente NovaAI Studio descrito acima. Os dois compartilham o nome "skill" e o formato
`SKILL.md`, mas são pipelines completamente separados (um roda dentro do Claude Code que edita
este repositório; o outro roda dentro do agente que o NovaAI Studio expõe aos usuários finais).

## 5. Aprovação e política (`agent/approval_policy.py`)

Opt-in, por projeto, guardada em `.novaai_studio/approval_policy.yaml`. Duas formas de regra:

- `EditPathRule`: glob simples (fnmatch) sobre o caminho + teto de linhas alteradas — calcula o
  diff de verdade antes de decidir (`compute_proposed_diff`), então "até 20 linhas" é sobre a
  mudança real, não uma estimativa.
- `ExecCommandRule`: prefixo de comando permitido, com uma lista de caracteres perigosos
  (`;`, `&`, `|`, `` ` ``, `$(`, `>`, `<`, `\n`) que desqualifica o match mesmo se o prefixo bater
  — `"npm test"` não aprova `"npm test && rm -rf /"`. Wrappers de shell (`bash`, `sh`, `pwsh`,
  `cmd`...) e `sudo` são sempre rejeitados, mesmo com prefixo aparentemente ok.

Fail-closed em toda borda: regra malformada, diff incalculável, exceção na avaliação — tudo vira
"não casou", nunca "aprovado por omissão". Nenhuma regra aprova `WRITE`/`EXEC` **fora** do que
descreve explicitamente.

`second_opinion` (bool, mesma política): quando ligado, toda ação que sobra para aprovação humana
recebe uma segunda opinião automática de outro modelo (`request_review_verdict`) — puramente
consultiva, uma falha vira `"unavailable"`, nunca `"approved"` silencioso, e o veredito nunca
realimenta a política (evita um modelo barato "carimbando" aprovações).

## 6. Contexto adicional que o usuário injeta manualmente

- **Arquivos/pasta em foco** (`focus_files`/`focus_folder`): chips no `AgentChatInput.tsx`,
  adicionados via botão "arquivo ativo" ou input de pasta — vira uma seção fixa no prompt da
  tarefa (`prompts.py:236-246`). Não há busca fuzzy nem um sistema de `@menção` (`@arquivo`,
  `@pasta`, `@docs`, `@web`) — é point-and-click sobre o que já está aberto/digitado.
- **Imagens**: cole (Ctrl+V) ou upload, viram base64 anexado à mensagem — sem OCR/análise prévia
  no frontend, vai cru para o modelo.
- **Slash-hint no input** (`AgentChatInput.tsx:225-230`): ao digitar `/`, aparece um rodapé com
  `/explain /fix /test /refactor /docs`. **Isso é só uma dica visual** — nada no código intercepta
  o texto digitado para expandir `/fix` em um prompt estruturado ou mudar o modo automaticamente;
  o texto literal `/fix ...` vai para o agente como qualquer outra mensagem.
- **Instruções do projeto** (`.novaai_studio/instructions.md`, editável na aba "Instruções" do
  popover): texto livre concatenado ao system prompt em toda sessão nova (seção 2).

## 7. Aceitar/rejeitar código gerado

`InlineDiffApprovalBar.tsx` é a barra que aparece no editor quando o conteúdo em disco
(`headContent`) diverge do que o agente propôs (`content`) — botões "Aceitar no projeto"
(`Alt+Enter`) / "Descartar" (`Shift+Alt+Backspace`) / alternar lado-a-lado. **Isso é a UI de
revisão de uma edição já gerada pelo agente em turno completo** — não existe um fluxo de seleção
de código → instrução pontual → edição inline gerada ali mesmo (o equivalente ao `Cmd+K` do
Cursor/Copilot). Toda geração de código passa pelo ciclo completo think→approve→act do agente.

## 8. O que "modo agente" e "modo plan" garantem hoje, resumido

- **Modo Plan realmente bloqueia escrita** até o primeiro `write_todos` — no nível de schema de
  ferramentas oferecido ao modelo, não só por instrução textual.
- **Modo Plan não é "gerar plano e parar"** — depois do primeiro `write_todos`, o mesmo turno (ou
  os seguintes) já pode escrever arquivos livremente; não há um segundo gate de confirmação
  humana entre "plano registrado" e "começou a editar".
- **Nenhum modo tem prompt dinâmico por complexidade de tarefa** — o mesmo `SYSTEM_PROMPT` de 200
  linhas roda para qualquer tamanho de pedido.
- **Aprovação humana (`interrupt()`) é ortogonal ao modo** — `auto` não pula aprovação de ações
  `WRITE`/`EXEC` sem uma `ApprovalPolicy` explícita; "automático" aqui significa "não pausa para
  perguntar se deve continuar a tarefa", não "não pausa para aprovar mudanças arriscadas".

## 9. Índice de arquivos-fonte

| Camada | Arquivo |
| --- | --- |
| System prompt + prompt por modo | `apps/api/src/novaai_studio/agent/prompts.py` |
| Ciclo think/approve/act, gate de ferramentas por modo | `apps/api/src/novaai_studio/agent/graph.py` |
| Política de auto-aprovação | `apps/api/src/novaai_studio/agent/approval_policy.py` (+ `approval_policy_config.py`, `approval_policy_editor.py`) |
| Ferramentas de skills do agente | `apps/api/src/novaai_studio/agent/tools/skills.py` |
| Ferramenta de plano/checklist | `apps/api/src/novaai_studio/agent/tools/plan.py` |
| Serviço/store de skills (Postgres) | `apps/api/src/novaai_studio/skills/service.py`, `store.py` |
| Seed de skills a partir de `.agents/` | `apps/api/src/novaai_studio/skills/seed.py` |
| Skills curadas do projeto | `.agents/skills/master-*/SKILL.md` (12 arquivos) |
| Skills vendorizadas (Addy Osmani) | `.agents/agent-skills/skills/*/SKILL.md` (~25 arquivos) |
| Regras de modo planejamento (doc) | `.agents/rules/planning_mode.md` |
| Fonte única de texto dos 7 modos (frontend) | `apps/web/components/ide/agent/modes.ts` |
| Popover de Personalizações (modos, skills, instruções, aprovação) | `apps/web/components/ide/agent/CustomizationsPopover.tsx` |
| Input do chat (chips, slash-hint, imagens) | `apps/web/components/ide/agent/AgentChatInput.tsx` |
| Barra de aceitar/rejeitar diff no editor | `apps/web/components/ide/InlineDiffApprovalBar.tsx` |
