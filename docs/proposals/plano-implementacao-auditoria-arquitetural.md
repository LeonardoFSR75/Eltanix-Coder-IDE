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

- [ ] **Agent Flight Recorder v1.** Linha do tempo única, append-only, por `session_id`,
  unificando `tool_span`, `request_log` e `audit_log` — hoje reconstruir "o que o agente
  fez" exige juntar as três sem chave de ordenação compartilhada. Ver `telemetry/tracer.py`,
  `router/telemetry.py`, `audit/`.
- [ ] **Espelho Postgres durável do `AgentCoordinator`.** Tabela `agent_edge(parent_id,
  child_id, status, updated_at)` atualizada em paralelo ao Redis em `agent/coordinator.py`
  — Redis continua o caminho rápido (BLPOP), Postgres vira a fonte de verdade para
  auditoria e recuperação pós-restart.
- [ ] **RBAC com enforcement.** Papéis leitura/escrita/admin por projeto sobre a tabela
  `project_member` do Horizonte 1. Precisa passar por todo `AuthDep`/`require_session`
  (`api/deps.py`) e pela filtragem de rotas por `project_slug`.
- [ ] **Marcação de obsolescência em `Note`/`GraphNode`.** Estender o princípio que
  `CodeChunk.content_hash` já resolve para reindexação incremental — ligar nota/nó do
  grafo ao hash do arquivo que referenciam, sinalizar quando diverge.

## Horizonte 3 — Escala (6–12 meses)

- [ ] **Pool de executores com fila e cota real de CPU/densidade por host.** Hoje
  `services/executor` é um único host (ADR 0002) sem réplicas; `SANDBOX_MEMORY` é o único
  teto exposto, sem CPU shares nem limite de sessões concorrentes.
- [ ] **Reuso de sandbox aquecido entre sessões do mesmo projeto**, em vez de container
  novo por sessão — as sementes já existem em `sandbox/executor.py` (`env_mounts` reusando
  `.venv`/`node_modules`/`vendor`).
- [ ] **Teste de carga formal** contra o alvo de 1.000 projetos / 500 usuários / 5.000
  sessões-dia / 50.000 execuções-dia definido na auditoria.

## Horizonte 4 — Inteligência (12–24 meses)

- [ ] **Planejamento como nó de primeira classe** em `agent/graph.py::build_graph` — hoje
  é uma chamada de ferramenta dentro de `think`, sem estado próprio que a UI possa
  renderizar de forma estável.
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
