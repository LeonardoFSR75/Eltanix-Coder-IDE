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
- [ ] **Schema `project_member`** (sem enforcement ainda — só a tabela). Nova migração
  Alembic em `apps/api/src/sicoobito/db/alembic/versions/`, modelo em `db/models.py` ao
  lado de `AppUser`/`ProjectRecord` (o docstring de `AppUser` já reserva esse espaço).
- [ ] **FK real em `workspace`/`project_slug`.** Hoje `IndexedFile`/`CodeChunk`/`GraphNode`
  usam `workspace` como string solta e `Document`/`Note` usam `project_slug` nulável, sem
  FK para `ProjectRecord`. Endurecer a escrita (validar contra `ProjectRecord.slug`) antes
  de qualquer FK de banco, para não quebrar dado existente sem migração de backfill.
- [ ] **Reclamar sessões zumbi.** `AgentSessionRecord.status` fica `"open"` para sempre
  quando uma aba fecha sem `close_session` explícito. Sweep periódico (mesmo padrão do
  `run_reaper` em `sandbox/executor.py`) que marca como `"abandoned"` após N horas sem
  `updated_at` avançar.
- [ ] **`actor`/`user_id` em `RequestLog`.** Coluna nova, aditiva, sem quebra — pré-requisito
  para faturamento por usuário quando o RBAC entrar em vigor. `db/models.py::RequestLog`.
- [ ] **Elevar `_SCRYPT_N`** em `auth/service.py` de `2**14` para `2**17`, com rehash
  preguiçoso: versionar o prefixo de `password_hash` e recalcular no próximo login
  bem-sucedido, sem migração de dados.
- [ ] **Promover o E2E golden-path para gate de PR.** Hoje `.github/workflows/e2e.yml` só
  roda manual/noturno. Extrair o smoke mínimo (login + Monaco carrega) para um job leve
  em `ci.yml` — o custo de orquestrar a stack inteira já foi pago no design do workflow
  noturno, só falta um subconjunto barato por PR.
- [ ] **Documentar a senha admin no primeiro boot.** Fricção sentida na própria auditoria:
  sem `SICOOBITO_ADMIN_PASSWORD` fixado no `.env`, a senha só existe em log
  (`auth.seed_user.generated_password`). Adicionar ao README/onboarding um passo explícito
  antes do primeiro `docker compose up`.

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
- [x] Primeira melhoria implementada e validada ao vivo: criação de projeto não bloqueia
  mais em provisionamento de ambiente (`api/routes/projects.py`).
- [ ] Próximo item recomendado do Horizonte 1: schema `project_member` ou reclamação de
  sessões zumbi — ambos aditivos, baixo risco, sem dependência do item acima.
