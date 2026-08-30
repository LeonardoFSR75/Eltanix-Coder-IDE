# ADR 0016 — `ProjectRecord.local_path` é a fonte de verdade da localização do projeto

**Status:** aceito · **Data:** 2026-08-30

## Contexto

A revisão completa da gestão de projetos (parte do upgrade da IDE, ver
`docs/security_review_2026-08.md` e a sessão de revisão que originou este
ADR) encontrou duas fontes de verdade divergentes para "onde o projeto está
no disco":

- `POST /api/projects/open-path` grava `ProjectRecord.local_path` com
  **qualquer** pasta do host, autorizada explicitamente no `PathGuard`
  (`workspace/path_guard.py`) — pensado desde o início para vincular pasta
  fora de `PROJECTS_ROOT` (ver `LinkProjectModal.tsx`, aba "Vincular Pasta
  Existente").
- Todo o resto — leitura/escrita de arquivo (`workspace.py::project_fs`),
  sessão de agente (`agent.py`, `agent/runner.py`), indexação semântica
  (`context.py`), LSP (`lsp.py`), gestão de pacotes (`packages.py`), git
  (`git.py` via `WorkspaceFS`), board Trello (`trello.py`), Graphify
  (`graphify/api/router.py`) — resolve o projeto via
  `workspace/projects.py::resolve(projects_root, slug)`, que **ignorava**
  `local_path` e só sabia achar `PROJECTS_ROOT/<slug>`.

Resultado: um projeto vinculado via `open-path` aparecia no Hub 360° com
branch e commits (o único código que já lia `local_path` diretamente, em
`get_project_summary`), mas **não abria arquivo, não rodava o agente, não
indexava e não tinha LSP** — 400 "Projeto não encontrado". Pior: se existisse
uma pasta de mesmo nome sob `PROJECTS_ROOT`, tudo "funcionava" — só que
operando na pasta errada, enquanto o Hub mostrava os metadados da pasta
correta.

## Decisão

**`ProjectRecord.local_path` é a fonte de verdade.** `resolve()` passa a
consultá-lo antes do fallback legado (`PROJECTS_ROOT/<slug>`), então os ~8
pontos de chamada acima passam a funcionar sem nenhuma alteração — a
correção fica inteira dentro de `resolve()`.

O desafio prático: `resolve()` é síncrono e chamado de lugares sem sessão de
banco à mão (dependências FastAPI, funções de workspace). Threadar
`AsyncSession` por 8 arquivos só para ler uma coluna seria um refactor muito
maior do que o problema justifica. A solução é um **cache em memória**
(`_slug_to_local_path`, `workspace/projects.py`) — o mesmo padrão que
`default_path_guard` já usa:

- Populado sempre que uma rota já tem a sessão de banco em mãos e grava
  `local_path`: `open-path` (registra) e `delete` (evicta).
- Rehidratado do Postgres em dois pontos, espelhando exatamente como o
  `PathGuard` já se rehidrata: na subida da API (`main.py::lifespan`, best-
  effort) e sempre que a Central de Projetos lista (`sync_projects_db`).
- `resolve()` só usa a entrada do cache se o caminho **ainda existe** e está
  **autorizado** (dentro de `PROJECTS_ROOT` ou explicitamente permitido pelo
  `PathGuard`) — nunca confia cegamente numa entrada obsoleta.

## Consequências

- Projeto vinculado fora de `PROJECTS_ROOT` via `open-path` agora funciona
  ponta a ponta: arquivo, agente, índice semântico, LSP, pacotes, git,
  Trello, Graphify — todos resolvem para o caminho certo.
- `delete_project` foi corrigido para resolver o `target_path` **antes** de
  apagar o registro/evictar o cache (senão `resolve()` não teria mais como
  achar um projeto externo para o `rmtree` opcional) — e para evictar o
  cache mesmo quando `delete_files=False`, senão um slug reaproveitado por
  `create_project` herdaria o `local_path` do projeto apagado até o próximo
  restart.
- O cache é em memória e por processo — como o `PathGuard`, não sobrevive a
  um restart sem a rehidratação em `lifespan`. Múltiplas réplicas da API
  (fora do escopo atual, single-instance) precisariam de um cache
  compartilhado (Redis) em vez deste dict local.
- `list_projects(projects_root)` (o scanner puro de disco, "compatibilidade
  legada") continua sem saber de `local_path` — ele varre só
  `PROJECTS_ROOT`, de propósito, e não faz parte deste ADR.

## Alternativas consideradas

- **Threadar `AsyncSession` pelos ~8 pontos de chamada**, transformando
  `project_fs` e afins em dependências assíncronas com acesso a banco —
  tecnicamente mais "correto" (sem cache, sem risco de defasagem), mas um
  refactor de escopo muito maior para o mesmo resultado observável. Fica
  como direção futura se o cache em memória se mostrar insuficiente (ex.:
  quando a API rodar em múltiplas réplicas).
- **Opção B do plano original — `PROJECTS_ROOT` como única fronteira**,
  removendo `open-path`/`PathGuard` e usando symlink/junction para pasta
  externa. Descartada: reduziria risco e código, mas remove a
  funcionalidade de "vincular qualquer pasta do PC" que a UI já promete e
  que o produto quer manter.
