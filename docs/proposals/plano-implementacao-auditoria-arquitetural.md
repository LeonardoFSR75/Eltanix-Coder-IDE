# Plano de Implementação — Auditoria Arquitetural (2026-08-16)

Plano de execução passo a passo derivado do **Dossiê SicoobitoCode** (auditoria de
comitê multi-perspectiva, ver histórico da sessão de 2026-08-16). Cada item referencia
os arquivos concretos a tocar. Marcar `[x]` conforme for implementado — este documento
é reindexado pelo Graphify a cada `--update`, então vira nó consultável no grafo de
conhecimento do repositório.

Contexto da auditoria: placar de maturidade 0–5 por domínio (Arquitetura Geral 4,
Multi-Projeto 2, Agente 3.5, Memória 2.5, Segurança 4, Observabilidade 3, DX 3,
Governança 2) e 8 riscos ranqueados por impacto — os três primeiros (ausência de RBAC,
isolamento multi-projeto por string sem FK, coordenador multiagente Redis-only) formam
o núcleo de todo o roadmap abaixo.

## Horizonte 1 — Fundação (0–3 meses)

- [x] **Investigar e corrigir a falha de criação de projeto.** Causa raiz: `create_project`
  chamava `ensure_project_env` (cria `.venv`/`node_modules`) de forma síncrona — podendo
  levar dezenas de segundos num bind mount do Windows — e essa chamada é redundante com
  `POST /{slug}/prewarm`, que já refaz o mesmo provisionamento quando o usuário abre o
  projeto na IDE. Corrigido em `apps/api/src/sicoobito/api/routes/projects.py`: o
  provisionamento agora dispara como task em segundo plano (`asyncio.create_task`), sem
  bloquear a resposta. Validado ao vivo: resposta caiu para ~1,9s, com `.venv` sendo
  criado de fato em segundo plano (confirmado via log `packages.venv.creating`).
- [x] **Schema `project_member`** (sem enforcement ainda — só a tabela). Implementado:
  migração `alembic/versions/0018_project_member.py` + modelo `ProjectMember` em
  `db/models.py`, exatamente no nome que o docstring de `AppUser`/`0012_auth.py` já
  reservava. `role` string livre (owner/editor/viewer). Validado ao vivo: migração
  aplicada contra o Postgres real, round-trip via SQLAlchemy confirmado.
- [x] **Endurecer a escrita de `workspace`/`project_slug` (passo pré-FK).** Mapeados todos
  os pontos de escrita das quatro fontes de RAG: `context/` e a varredura de diretório do
  `graphify/` já eram seguros (workspace = caminho absoluto resolvido por
  `workspace/projects.py::resolve`, com proteção de path traversal). Os gaps reais eram
  `documents.py::request_upload_url`, `notes/service.py::create` e o ramo de indexação de
  conteúdo avulso do `graphify/api/router.py::index_content` (nota/documento/arquivo único,
  fora da varredura de diretório) — todos aceitavam `project`/`project_slug` como string
  livre do request body, sem checar contra nenhum projeto real. Adicionado
  `ensure_project_slug_exists` em `workspace/projects.py` (não é uma das quatro stores, não
  fere a regra de não abstrair a duplicação) e conectado nos três pontos, convertendo
  `ProjectError` em 400; `project_slug=None`/`project` vazio continua permitido (nota/
  documento "global"). FK de banco de verdade com migração de backfill fica para quando
  fizer sentido — este endurecimento já fecha o buraco de escrita sem mexer em schema.
  Validado ao vivo contra a stack real: slug inexistente → 400 em `/api/documents/upload-url`,
  `/api/notes` e `/api/graphify/index`; slug real (`Mestrado`) e projeto vazio (global) → 200.
  Suíte completa (562 testes) sem regressão — as 2 falhas encontradas (mojibake de encoding
  num teste de browser, um teste de `agent_finish` desalinhado) são pré-existentes e
  não relacionadas, confirmado rodando-as contra o código sem esta mudança via `git stash`.
  Durante a validação ao vivo, achado um bug real e não relacionado (mismatch de dimensão
  de embedding, 768 vs 1024, quebrando toda criação de nota/documento) — não corrigido aqui
  por estar fora de escopo, encaminhado como task separada.
- [x] **Reclamar sessões zumbi.** `AgentSessionRecord.status` ficava `"open"` para sempre
  quando uma aba fechava sem `close_session` explícito. Implementado:
  `AgentRunner.run_zombie_session_reaper` (`agent/runner.py`) + `session_store.
  mark_abandoned` (`agent/session_store.py`), mesmo padrão de `SandboxManager.run_reaper`
  e `AuthService.run_session_purge_reaper`, laço horário, limiar configurável via
  `AGENT_SESSION_ABANDON_AFTER_HOURS` (default 24h). Validado ao vivo: reclamou 192
  sessões `"open"` órfãs desde 08/08 nesta base de dev local.
- [x] **`actor` em `RequestLog`.** Coluna nova, aditiva, populada por `identify_actor`
  (`api/deps.py`) — `"api_key"` para o canal de serviço ou username da sessão. Threading
  até `RouterEngine.complete/stream/embed` via closure local (evita editar os 9 pontos de
  chamada de `TelemetryEntry`). Validado ao vivo: `POST /v1/chat/completions` real gravou
  `actor="api_key"`.
- [x] **Elevar `_SCRYPT_N`** em `auth/service.py`. `2**17` (o teto da OWASP) mediu ~2,7s
  por hash neste hardware — trocado por `2**16` (~1s, ainda 4x mais caro que o valor
  antigo). Formato do hash agora carrega os próprios parâmetros (`n$r$p$salt$hash`);
  rehash automático no próximo login bem-sucedido, sem migração de dados. A validação ao
  vivo pegou um bug real que os testes não cobriam: `_verify_password` comparava a string
  formatada inteira em vez dos bytes derivados, o que faria todo hash legado falhar
  sempre — corrigido no mesmo commit.
- [x] **Promover o E2E golden-path para gate de PR.** Reconsiderado durante a implementação:
  o custo é o de SUBIR a stack inteira, não o de quantos testes rodam nela — "só o smoke
  leve" não reduziria o tempo real. Solução aplicada: `pull_request` filtrado por caminho
  em `.github/workflows/e2e.yml` (só dispara quando `apps/web`, rotas de projeto/navegador,
  auth ou `docker-compose.yml` mudam); push fora desses caminhos continua só no noturno.
- [x] **Documentar a senha admin no primeiro boot.** `README.md` e `.env.example` agora
  explicam `SICOOBITO_ADMIN_PASSWORD` antes do primeiro `docker compose up`.

## Horizonte 2 — Governança (3–6 meses)

- [x] **Agent Flight Recorder v1.** Investigação prévia (ver `telemetry/tracer.py`,
  `router/telemetry.py`, `audit/`) achou dois problemas, não um: as três fontes já
  compartilhavam `created_at` comparável (mesmo tipo, mesmo relógio Postgres), mas só
  `tool_span`/`audit_log` tinham `session_id` — `request_log` não tinha a coluna nem
  qualquer substituto, e `RouterEngine.complete/stream/embed` não aceitava `session_id`
  como parâmetro (mesmo com a sessão disponível no chamador, `agent/graph.py`, nunca
  atravessava a fronteira do router). Implementado: migração `0020` adiciona
  `request_log.session_id` (nulável, índice composto com `created_at`, mesmo padrão da
  `0019`/`actor`); `session_id` roteado por `RouterEngine.complete/stream/embed` via
  closure local (mesmo mecanismo já usado para `actor`) e passado pelos dois pontos reais
  de chamada dentro do fluxo do agente — `agent/graph.py::think()` e
  `agent/review_common.py::request_review_verdict()` (segunda opinião, chamada tanto de
  `graph.py::_attach_review_notes` quanto da tool `request_code_review`). Desviado da
  proposta literal do plano (tabela append-only nova): as três fontes têm payload
  genuinamente heterogêneo (não é duplicação), mas `tool_span`/`request_log` são
  fire-and-forget por design (perder uma linha é aceitável) e `audit_log` é síncrona —
  espelhar as três num quarto ponto de escrita herdaria o mesmo risco de perda sem
  eliminar a necessidade de nenhuma das três. `telemetry/flight_recorder.py::session_timeline`
  compõe as três por leitura (uma query cada, mescla e ordena por `created_at`), exposto em
  `GET /api/agent/sessions/{id}/timeline`. Testado: 4 testes de integração novos contra
  Postgres real (`test_flight_recorder.py`, `test_router_telemetry.py`) cobrindo
  merge/ordenação e persistência de `session_id`; suíte completa sem regressão (3 fakes de
  `RouterEngine` em testes existentes precisaram aceitar o novo kwarg `session_id`).
  Validado ao vivo: `GET /api/agent/sessions/{id}/timeline` numa sessão real com atividade
  em `tool_span` e `audit_log` devolveu os 47 eventos mesclados e corretamente ordenados
  por `created_at` (sessão anterior a esta mudança, por isso sem eventos `request_log` —
  esperado, a coluna é nova).
- [x] **Espelho Postgres durável do `AgentCoordinator`.** Desviado da proposta literal do
  plano: uma tabela `agent_edge` nova duplicaria dado que `agent_session` (`AgentSessionRecord`,
  já criado no item "Reclamar sessões zumbi" deste horizonte) já persiste — `parent_session_id`
  é a mesma lineage que `agent_edge` propunha guardar separada, e mantê-la em dois lugares
  arriscaria os dois divergirem. Implementado como fallback de leitura em vez de espelho de
  escrita: `session_store.graph_snapshot` (`agent/session_store.py`) reconstrói a árvore
  pai/filho via BFS em `agent_session`; `AgentCoordinator.graph_snapshot`
  (`agent/coordinator.py`) tenta o Redis primeiro (`_graph_snapshot_from_redis`, caminho
  rápido inalterado) e só recorre ao Postgres (`_graph_snapshot_from_db`) quando o Redis
  devolve árvore vazia — indisponível ou TTL expirado após um restart. A árvore reconstruída
  do banco tem vocabulário de status mais grosso (open/closed/abandoned em vez de
  running/waiting_approval/...), suficiente para auditoria/recuperação, não para o
  caminho ao vivo. Testado: suíte unitária (`test_agent_coordinator.py`,
  `test_session_store.py`) sem regressão; dois testes de integração novos contra Postgres
  real (`pg_session`) cobrindo o fallback (árvore com filho, raiz inexistente). Validado ao
  vivo contra a stack real: `GET /api/agent/sessions/{id}/graph` numa sessão-pai com
  filho, ambas horas fora do TTL do Redis (confirmado `EXISTS` = 0 nas duas chaves Redis),
  devolveu a árvore correta (`depth`, `parent_id`, `children` certos) inteiramente a partir
  do Postgres.
- [x] **RBAC com enforcement.** Três papéis, rank crescente (`auth/rbac.py::ROLE_RANK`):
  `viewer` (leitura) < `editor` (escrita) < `owner` (admin do projeto — atualiza, apaga,
  gerencia membro) sobre a tabela `project_member` do Horizonte 1. Decisão de produto (via
  pergunta ao usuário, já que o sistema era single-user/seed-only): admin cria usuário
  via API — `POST /api/auth/users` (`AdminDep`, `api/deps.py::require_admin`), sem
  self-signup nem convite por e-mail. Migração `0021_app_user_is_admin.py` adiciona
  `AppUser.is_admin` e promove o usuário mais antigo (o seed original) a admin da
  instância — dono da instância e canal de serviço (`SICOOBITO_API_KEY`, ADR 0005) sempre
  passam sem consultar `project_member` (`auth/rbac.py::_actor_bypasses`), o mesmo espírito
  de "canal de serviço não é usuário de browser" que já rege `require_session`.
  Enforcement por rota, não por um dependency FastAPI único: `project_slug` chega por
  caminho diferente em cada arquivo (path param em `projects.py`, query/body em
  `context.py`/`documents.py`/`notes.py`, campo derivado de um `ProjectRecord` já
  carregado em outros) — mesma razão pela qual RAG já mantém fontes independentes em vez
  de um helper compartilhado. `require_role_by_slug` é tolerante por desenho: `None` (nota/
  documento/busca global) e slug que não bate com nenhum `ProjectRecord` (projeto ad-hoc)
  não fazem nada, preservando o comportamento de hoje — RBAC só existe *por projeto*, não
  há papel "global". Cobertura: lifecycle completo de `projects.py` (create/update/delete/
  summary/prewarm/open-absolute-path) mais as novas rotas `GET|POST /{slug}/members` e
  `DELETE /{slug}/members/{user_id}`; `context.py` inteiro (projeto é sempre obrigatório
  ali); `documents.py`/`notes.py` só quando um projeto é de fato passado (skip no
  conteúdo global, mesmo raciocínio tolerante); `POST /api/agent/sessions` (criação, com
  o mesmo skip tolerante já que `payload.project` é nome de pasta em `PROJECTS_ROOT`, não
  garantidamente um slug registrado). Fora de escopo, deliberadamente: `graphify/api/
  router.py` — seu `workspace` não é de forma confiável o mesmo identificador que
  `ProjectRecord.slug`, e `/query/multi` é documentado como busca cross-workspace por
  desenho, então mapear para RBAC por projeto precisa de desenho próprio, não um bolt-on;
  as subrotas `/api/agent/sessions/{id}/*` (além da criação) — não existe hoje nenhum
  conceito de "quem pode agir na sessão X" (qualquer chamador autenticado que saiba o
  `session_id` age nela), lacuna pré-existente mais ampla que este item de RBAC. Bug de
  privilégio encontrado e corrigido no caminho: `POST /api/projects` agia como upsert por
  slug sem checagem nenhuma no ramo de atualização — qualquer chamador autenticado podia
  reescrever metadado de projeto já existente sem ser dono, contornando por completo o
  `editor` exigido por `PATCH /{slug}`; fechado com `require_role_by_slug(min_role="editor")`
  antes da mutação. Armadilha revisitada duas vezes: `except Exception` largo em
  `create_project`/`get_summary` (degrada-e-segue, ver seção de Segurança do `CLAUDE.md`
  raiz) engoliria silenciosamente o `HTTPException(403)` do RBAC e devolveria 200 pelo
  fallback — corrigido com `except HTTPException: raise` antes do `except Exception`
  genérico em `create_project`, e evitado em `get_summary` colocando a checagem num bloco
  `session_scope()` próprio, fisicamente fora do `try/except`. Testado: 13 testes de
  integração novos contra Postgres real (`test_rbac.py`, fixture `pg_session`) cobrindo
  rank de papel, os dois bypasses, tolerância a slug `None`/não-registrado, e CRUD de
  `project_member` (`add_member` como upsert, `remove_member`, `list_member_project_ids`);
  suíte completa (573 testes) sem regressão — 2 falhas pré-existentes e não relacionadas
  (encoding de console Windows em `test_agent_tools.py`, comportamento de
  `agent_finish` em `test_agent_tools_agents_graph.py`), confirmadas por não estarem no
  diff desta mudança. Validado ao vivo contra a stack real via `docker compose`: criado
  usuário não-admin via `POST /api/auth/users`, adicionado como `viewer` a um projeto de
  teste — confirmado que lê `GET /{slug}/summary` (200) mas `PATCH`/`DELETE`/adicionar
  membro/criar nota no projeto devolvem 403; promovido a `editor` — criar nota passa a
  200, `DELETE` do projeto continua 403 (precisa `owner`); removido da membership —
  `GET /{slug}/summary` volta a 403. Projeto e sessão de teste removidos ao final.
- [ ] **Marcação de obsolescência em `Note`/`GraphNode`.** Estender o princípio que
  `CodeChunk.content_hash` já resolve para reindexação incremental — ligar nota/nó do
  grafo ao hash do arquivo que referenciam, sinalizar quando diverge.

## Horizonte 3 — Escala (6–12 meses)

- [x] **Pool de executores com fila e cota real de CPU/densidade por host.** Escopo
  reduzido deliberadamente (via pergunta ao usuário): o texto original do item mirava
  o alvo de escala da auditoria (500 usuários / 5.000 sessões-dia), que pede pool
  multi-host com broker — infraestrutura que o produto, local-first e efetivamente
  single-machine hoje, não opera nesse nível. Investigação encontrou que
  `mem_limit`/`cpu_quota`/`pids_limit` por sandbox já existiam (`services/executor/
  app.py`, `sandbox/container.py`) — a lacuna real era ausência de teto no *número* de
  sandboxes simultâneos e de qualquer mecanismo de fila. Implementado:
  `sandbox/concurrency.py::SandboxConcurrencyGate`, fila FIFO em processo (sem broker,
  sem réplica) — `asyncio.Event` por esperador, `acquire(session_id)` bloqueia até
  haver vaga (idempotente: sessão já ativa retorna na hora, cobrindo reconexão sem
  competir de novo), `release(session_id)` promove o próximo da fila, cancelamento
  durante a espera (`CancelledError`) remove o esperador sem vazar vaga. Cabeçalho novo
  `SANDBOX_MAX_CONCURRENT` (default 6, `config.py`) plugado em ambos os gerenciadores —
  `SandboxManager.acquire`/`.release` (`sandbox/container.py`, modo dev local) e
  `ExecutorSandboxManager.acquire`/`.release` (`sandbox/executor.py`, modo produção via
  ADR 0002) — só a criação de sandbox *novo* passa pela fila; reaproveitar o sandbox já
  ativo de uma sessão (cache hit) não consome vaga de novo. Posição na fila exposta via
  `GET /api/agent/sandboxes/queue` (`api/routes/agent.py`) — endpoint de polling em vez
  de reestruturar `create_session` num fluxo assíncrono explícito, já que o loop de
  eventos do uvicorn continua servindo outras requisições enquanto uma corrotina espera
  vaga. Testado: 7 testes novos unitários do gate (`test_sandbox_concurrency.py`,
  cobrindo limite, FIFO, idempotência, no-op de `release` sem `acquire` prévio,
  cancelamento sem vazamento de vaga, piso de `max_concurrent=1`); suíte completa (574
  testes) sem regressão nova — mesmas 2 falhas pré-existentes de antes. Validado ao vivo
  contra a stack real (modo executor, `sandbox.mode=executor`): `GET /sandboxes/queue`
  antes de criar sessão devolveu `active=0`; `POST /api/agent/sessions` num projeto real
  (`e2e-smoke-test`) fez `active` subir para `1`; `POST /sessions/{id}/close` devolveu
  para `active=0` — ciclo completo de aquisição/liberação confirmado ponta a ponta.
- [x] **Reuso de sandbox aquecido entre sessões do mesmo projeto** — investigado e
  **deliberadamente não implementado** (via pergunta ao usuário): a premissa do item não
  se sustenta na forma como está escrita. A parte cara de "aquecer" um sandbox é instalar
  dependências, e isso **já é compartilhado** entre sessões do mesmo projeto hoje —
  `env_mounts` resolve `.venv`/`node_modules`/`vendor` por caminho canônico do projeto
  (subindo por `.sicoobito/worktrees/` até a raiz) tanto em `sandbox/executor.py::
  RemoteSandbox.start` quanto em `sandbox/container.py::Sandbox.start`, e o executor
  (`services/executor/app.py::create_sandbox`) monta os mesmos diretórios de host para
  qualquer sessão do projeto. O que sobra — o próprio `docker run` — já é rápido (segundos,
  não minutos) porque a imagem já está local e o volume é bind mount, não cópia. Container
  em si é hoje reaproveitado só por `session_id` exato (`_container_cache`/nome do
  container em `services/executor/app.py:248` e `sandbox/container.py::Sandbox.start`),
  cobrindo reconexão após reload, não sessão nova do mesmo projeto — e essa é uma escolha
  correta, não uma lacuna: um pool de containers ociosos por projeto (opção descartada)
  trocaria segundos de `docker run` por gestão de TTL/claim/release e risco real de estado
  residual (arquivo temporário, processo, variável de ambiente) vazando de uma sessão para
  a próxima que reivindicar o mesmo container — pior troca que o problema que resolveria.
- [x] **Teste de carga formal** contra o alvo de 1.000 projetos / 500 usuários / 5.000
  sessões-dia / 50.000 execuções-dia definido na auditoria — escopo reduzido via
  pergunta ao usuário: o alvo da auditoria pressupõe infraestrutura multi-tenant que o
  produto não opera hoje (local-first, single-machine), então não faz sentido tentar
  provar esse número especificamente. Implementado em vez disso um smoke de
  concorrência (`apps/api/scripts/load_test_sandbox_queue.py`) que valida o gate do
  item 1 sob carga real, concorrente, contra a stack `docker compose` — não a escala do
  alvo, mas o comportamento sob contenção que o gate promete. Script abre N sessões de
  agente concorrentes (`POST /api/agent/sessions`) contra um projeto real, faz *polling*
  de `GET /api/agent/sandboxes/queue` em paralelo, fecha cada sessão assim que a criação
  responde, e verifica ao final que a fila volta a `active=0`/`waiting=[]` sem exceção
  em nenhuma chamada. Autentica pelo canal de serviço (`SICOOBITO_API_KEY`, ADR 0005) —
  é ferramenta externa, não sessão de browser. Rodado ao vivo contra a stack real (modo
  executor): com 10 sessões concorrentes, pico de `active` observado bateu exatamente no
  teto (`max_concurrent=6`), houve fila (`waiting` chegou a 1) e o estado final voltou
  limpo, zero falhas; repetido com 15 sessões, mesmo resultado (pico de `active=6`, zero
  falhas). `docker ps` confirmou nenhum container `sicoobito-*` órfão depois — nenhuma
  vaga do gate vazou sob concorrência real. Achado incidental durante a primeira
  tentativa (timeout de 10s no polling): sob 6+ criações de sessão concorrentes o
  servidor de dev demora a responder a outras requisições por alguns segundos —
  provavelmente algum trabalho síncrono/bloqueante em `create_session` (worktree, git)
  não passa por `asyncio.to_thread`. Não investigado a fundo nem corrigido aqui —
  fora do escopo deste item (é sobre o gate de concorrência, não sobre a latência de
  criação de sessão em si); registrado para eventual investigação futura, não bloqueia
  o resultado do smoke (timeouts generosos no script absorvem isso, e a fila em si nunca
  vazou vaga nem devolveu estado inconsistente).

## Horizonte 4 — Inteligência (12–24 meses)

- [x] **Planejamento como nó de primeira classe** em `agent/graph.py::build_graph` —
  investigado e **deliberadamente não implementado** (via pergunta ao usuário): a
  motivação declarada no item não se sustenta mais. `write_todos` já popula
  `AgentState.todos` (`agent/state.py:59`) como campo próprio, não-acumulativo
  (substituído por inteiro a cada chamada, não somado como `messages`), e o frontend já
  tem um painel dedicado e sempre visível — `TodoCard.tsx` — renderizando essa lista como
  "Plano" com progresso (`N/total` completos), alimentado por `resultado.data["todos"]`
  que `act()` já extrai e expõe. O objetivo que o item persegue (UI com onde mostrar o
  plano de forma estável) já está atingido; o que sobraria é puramente uma reestruturação
  interna — mover `write_todos` de "chamada de ferramenta dentro de `act`" para um nó
  dedicado do LangGraph — sem benefício concreto identificado hoje (o gate de
  `_tool_schemas` por `has_plan` já impede os modos `plan`/`orchestra` de escrever/
  executar antes do primeiro `write_todos`, o que é o comportamento que "planejamento
  antes de agir" pede). `build_graph` é o loop `think → approve/act → think` que toda
  sessão de agente do produto atravessa — reestruturá-lo por uma motivação que já não se
  sustenta é risco alto sem contrapartida. Mesmo raciocínio dos itens 2 e 3 do
  Horizonte 3: premissa do item não resistiu à investigação, fechado sem código novo.
- [ ] **Promoção de padrões repetidos e bem-sucedidos a skills duráveis** (`skills/service.py`).
- [ ] **Especialização mais profunda de subagentes**, com replay via Flight Recorder.

## Horizonte 5 — Diferenciação (24–36 meses)

- [ ] **Exportação de auditoria pronta para compliance** (trilhas estilo SOC2) a partir do
  Flight Recorder e do `audit_log` já existente.
- [ ] **SSO empresarial** sobre a base de RBAC madura do Horizonte 2.
- [ ] **Oferta hospedada** ao lado do local-first, sem abrir mão da governança como
  diferencial de venda (ver seção estratégica do dossiê — nenhum concorrente listado expõe
  `RiskClass` + `approval_policy.yaml` versionável no mesmo nível).

## Progresso desta sessão

- [x] Dossiê publicado e revisado (2026-08-16).
- [x] Grafo de conhecimento (Graphify) e vault Obsidian atualizados para incluir este plano.
- [x] Criação de projeto não bloqueia mais em provisionamento de ambiente
  (`api/routes/projects.py`) — validado ao vivo.
- [x] Sessões de agente abandonadas são reclamadas periodicamente (`agent/runner.py`,
  `agent/session_store.py`) — validado ao vivo, 192 sessões reclamadas nesta base local.
- [x] Schema `project_member` criado e migrado (`db/models.py`, `alembic/versions/
  0018_project_member.py`) — maior alavancador do dossiê, pré-requisito para RBAC no
  Horizonte 2.
- [x] `_SCRYPT_N` elevado com rehash automático (`auth/service.py`) — validação ao vivo
  pegou e corrigiu um bug real de comparação de hash legado, não coberto pelos testes.
- [x] Coluna `actor` em `RequestLog` (`db/models.py`, `api/deps.py`, `router/engine.py`)
  — validado ao vivo via `POST /v1/chat/completions` real.
- [x] E2E promovido a gate de PR filtrado por caminho; senha admin documentada no README
  e `.env.example`.
- [x] **Horizonte 1 completo — 8 de 8 itens**, todos validados ao vivo contra a stack real.
  O último (`ensure_project_slug_exists` em `documents.py`/`notes/service.py`/
  `graphify/api/router.py`) endurece a escrita nas quatro fontes de RAG sem precisar de
  FK de banco nem migração de backfill — a FK de verdade fica para quando o custo de uma
  migração de backfill valer a pena, não é mais um bloqueador do horizonte.
- [x] Horizonte 2, item 2 — espelho Postgres durável do `AgentCoordinator`
  (`agent/coordinator.py`, `agent/session_store.py`) — validado ao vivo via
  `GET /api/agent/sessions/{id}/graph` numa árvore real fora do TTL do Redis; ver
  detalhe no item do horizonte acima. Horizonte 2, item 4 (marcação de obsolescência
  em `Note`/`GraphNode`) investigado e **deliberadamente não implementado nesta
  sessão**: a premissa do plano (estender `CodeChunk.content_hash`) não se sustenta —
  `GraphNode` não guarda hash de conteúdo nem caminho de arquivo, e `GraphChunkMapping`
  (que poderia ligar os dois) é código morto, sem nada escrevendo nela. Precisa de uma
  decisão de design (o que é "o arquivo que um nó do grafo referencia" para nó de
  ADR/import/tag) antes de virar implementação — não forçado sobre premissa errada.
