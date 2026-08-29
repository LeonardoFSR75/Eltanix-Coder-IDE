# ADR 0012 — Modos Customizáveis do Agente e o Gate de Ferramentas por Nome

**Status:** aceito · **Data:** 2026-08-29

## Contexto

Até a Fase 6 do upgrade do agente, os modos de execução eram 7 literais fixos
(`ask`, `edit`, `agent`, `plan`, `auto`, `orchestra`, `explore`), cada um
hardcoded em Python. O gate de ferramentas oferecido ao modelo
(`agent/graph.py::_tool_schemas`) era decidido por **classe de risco**: um modo
liberava `allow_write`/`allow_exec` e o registro filtrava as ferramentas
`READ`/`WRITE`/`EXEC` correspondentes.

A Fase 6 introduziu modos definidos pelo usuário (`agent_custom_mode`:
`name`, `icon`, `description`, `allowed_tools: JSON`, `prompt_block`). Isso
levanta duas questões que tocam invariantes documentados no `CLAUDE.md` raiz:

1. `AgentMode` deixou de ser `Literal[...]` e passou a ser `str` — um id de
   modo customizado circula como `mode` em toda a borda SSE/frontend.
2. Um modo customizado restringe as ferramentas por **lista explícita de
   nomes** (`allowed_tools`), não por classe de risco.

## Decisão

1. **`allowed_tools` é uma allowlist de nomes, aplicada por cima do gate de
   risco — nunca no lugar dele.** Em `_tool_schemas`, quando `mode` não é um
   dos 7 built-ins, o registro é filtrado para conter **apenas** os nomes em
   `allowed_tools`. A `RiskClass` de cada ferramenta permanece intacta: uma
   ferramenta `WRITE`/`EXEC` incluída num modo customizado **continua** parando
   no `interrupt()` de aprovação humana em `agent/graph.py::approve()`. Um modo
   customizado pode tornar uma ferramenta *indisponível*, nunca *auto-aprovada*.

2. **Fail-closed para modo não resolvido.** Se o id não casa com nenhum
   `agent_custom_mode` (id inválido, linha removida do banco, serviço fora),
   `_tool_schemas` cai para **somente leitura** — o mesmo conjunto do modo
   `ask` —, nunca para o toolset completo. `allowed_tools = []` (lista vazia
   salva de propósito) concede **nada**; é distinguível de `None` ("não
   resolvido") de propósito.

3. **Nomes de ferramenta são validados no save.** `POST`/`PUT
   /api/agent/custom-modes` rejeita (`422`) qualquer nome em `allowed_tools`
   que não exista em `registry.all()`, com a lista dos nomes inválidos — um
   modo não pode salvar "sujo" e falhar em silêncio depois.

4. **`AgentMode = str` com validação em runtime.** O tipo é aberto; a
   distinção "built-in vs id de modo customizado" é feita em runtime contra
   `state.py::BUILTIN_MODES`. `apps/web/.../modes.ts` continua com o `Mode`
   fechado nos 7 built-ins **apenas** para os botões fixos da UI; o caminho de
   runtime (`sessionTypes.ts`, `AgentChatInput.tsx`, `useAgentSessions.ts`)
   usa `string`.

## Alternativas consideradas

- **Modo customizado escolhe a classe de risco liberada** (`allow_write`
  etc.) em vez de nomes — não permite "só `read_file` e `search_code`", que é
  o caso de uso principal (revisor restrito a um subconjunto). Rejeitado.
- **Deixar o modelo obedecer só a instrução textual do `prompt_block`** sem
  gate de schema — o mesmo motivo pelo qual o "Modo Planejar" reforça o gate
  no schema (ADR implícito na Fase 3): instrução textual não é garantia.
  Rejeitado.
- **Manter `AgentMode` como `Literal` e mapear ids para um enum sintético** —
  espalha conversões frágeis por todo payload SSE. Rejeitado em favor de
  `str` + checagem central.

## Consequências

- Modos customizados nunca ampliam a superfície de risco: no pior caso
  (bug de resolução) o agente fica só-leitura.
- O invariante "aprovação humana é decidida pela ferramenta (RiskClass),
  nunca pelo chamador" continua válido — um modo customizado é um chamador.
- `modes.ts` e `_tool_schemas` precisam concordar sobre quais são os 7
  built-ins; `test_custom_modes.py::TestBuiltinModesConstant` e
  `test_slash_commands.py::test_every_suggested_mode_is_a_builtin_mode`
  travam isso.
