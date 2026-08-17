# SicoobitoCode

Plataforma local-first de codificação agêntica: um IDE web estilo VS Code com chat e agente
autônomo sobre o repositório, integração com Git/GitHub e um **gateway multi-modelo** que
roteia entre Ollama (local), Azure AI Foundry e Databricks com contabilidade de custo e
otimização de token.

O princípio que sustenta tudo: **nenhum módulo fala com um provedor de LLM diretamente**.
Toda chamada passa pelo router, e cada provedor entra como adaptador plugável — trocar de
modelo ou de nuvem é mudança de configuração, não de código.

## Estado atual

Além do IDE agêntico original (gateway multi-modelo, indexação de código,
agente LangGraph, editor Monaco), a plataforma cresceu para uma base de
conhecimento completa em torno do mesmo agente:

| Área | Escopo | Status |
|---|---|---|
| Gateway multi-modelo | Roteamento (Ollama, Azure, Databricks, Anthropic, Groq), fallback, custo, cache | validada |
| Contexto de código | Indexação tree-sitter + pgvector, busca híbrida (RRF) | validada |
| Agente | LangGraph, sandbox Docker, Git/GitHub, PRs, modos `ask`/`edit`/`agent`/`plan`/`auto`/`orchestra` | validada |
| IDE web | Monaco (split-pane), explorer com drag-and-drop, terminal, cards estruturados por tool-call, Agent Manager (múltiplas sessões) | validada |
| Verificação por navegador | Ferramenta `browser_action` (Chromium headless isolado em rede própria) | validada |
| RAG de documentos | Upload → MinIO + pgvector, busca híbrida, ferramenta do agente | validada |
| Segundo Cérebro | Notas com `[[wikilinks]]`, busca híbrida, ferramenta do agente | validada |
| Graph RAG (Graphify) | Base de Conhecimento em Grafo (nós/arestas L1-L3), expansão CTE/GQL, visualização 360° | validada |
| Skills & Memória | Catálogo de habilidades reutilizáveis (`addyosmani/agent-skills`, `MadsLorentzen/ai-job-search` e hub de memória `TencentCloud/TencentDB-Agent-Memory`), CRUD real e auto-seed | validada |
| Auditoria | Toda aprovação WRITE/EXEC do agente é registrada no Postgres | validada |
| MCP | Cliente real (stdio/HTTP), catálogo de conectores prontos (GitHub, filesystem, Postgres, Slack) | validada |
| Observabilidade | `TraceRecorder` (spans de tool/RAG), correlation ID ponta a ponta, avaliação hit@k/MRR de RAG | validada |
| Modo Orquestra | Ciclo TDD forçado por item de plano, revisão de código por chamada de LLM isolada, commit por etapa | validada |

Exercitado de ponta a ponta: as migrações contra Postgres real (pgvector,
índices HNSW/tsvector); indexação deste próprio repositório; sessão de agente
com worktree Git e sandbox Docker (usuário não-root, escrita barrada fora do
workspace, rede desabilitada); MCP conectado a um servidor real via `npx`;
busca híbrida e expansão em Grafo (Graphify) das fontes contra Postgres.

487 testes de backend (+ 27 pulados sem `DATABASE_URL_TEST`) e 26 de frontend.
Pytest, Vitest, `tsc` e `next build` limpos. CI no GitHub Actions roda tudo
isso a cada push/PR na `main`, mais auditoria de dependências.

## Requisitos

- **Docker** — é o único requisito de execução; toda a stack roda em containers,
  Ollama e language servers inclusive
- `uv` e Node só para rodar testes e lint fora dos containers
## Início rápido

Tudo roda em containers — um único `docker compose up`. Nenhuma parte fica no host.

Copie o `.env` e ajuste `PROJECTS_ROOT` para a pasta que contém seus projetos:

```bash
cp .env.example .env
```

Gere as duas chaves (`SICOOBITO_API_KEY` e `EXECUTOR_TOKEN`):

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

**Fixe também `SICOOBITO_ADMIN_USERNAME`/`SICOOBITO_ADMIN_PASSWORD` no `.env`** — é a
credencial de login do browser (`/ide`, ADR 0005), separada das duas chaves acima. Sem
isso, a API gera uma senha aleatória na primeira subida e só a mostra uma vez, no log
(`docker compose logs api | grep auth.seed_user`) — fácil de perder, e sem jeito de
recuperar depois sem redefinir a senha diretamente no banco.

```bash
docker compose up -d --build
```

```bash
docker compose exec api alembic upgrade head
```

Pronto — abra `http://localhost:5400/ide` e entre com o usuário/senha que você fixou
acima:

| Serviço | Porta | URL |
|---|---|---|
| IDE e dashboard (Next.js Web) | 5400 | http://localhost:5400/ide |
| IDE Desktop Preview (Svelte 5) | 5409 | http://localhost:5409 |
| API (gateway OpenAI-compatible) | 5401 | http://localhost:5401/v1 |
| Executor (interno) | 5402 | — |
| Postgres | 5403 | — |
| Redis | 5404 | — |
| Ollama | 5405 | http://localhost:5405 |


A faixa 5400–5499 foi escolhida para não disputar 3000, 8000 e 5432 com outros
projetos.

### Modelos locais (Ollama opcional)

Por padrão, a plataforma sobe leve usando provedores cloud (**Anthropic** ou **Databricks**, dependendo das chaves no `.env`). O Ollama local roda como um serviço opcional via perfil do Docker Compose — nada precisa ser instalado no host.

Para iniciar a plataforma **com o Ollama local**:
```bash
docker compose --profile ollama up -d
```

O serviço `ollama-init` baixa os modelos de `OLLAMA_PULL_MODELS` na primeira subida e sai; os pesos ficam num volume, então recriar containers não rebaixa nada.

```bash
docker compose --profile ollama logs -f ollama-init
```

**Sem GPU, o tamanho do modelo é a variável que decide se isto é usável.** Numa
máquina com gráficos integrados e 8 GB alocados ao Docker, o `qwen2.5-coder:1.5b`
responde em segundos e o `7b` entra em swap. Os perfis `auto` e `cheap` usam o
pequeno por isso; `local-first` e `coding` pedem o 7b, e só valem a pena com RAM
sobrando ou GPU. Para GPU NVIDIA, adicione ao serviço `ollama`:

```yaml
    deploy: { resources: { reservations: { devices: [{ capabilities: [gpu] }] } } }
```

O gateway responde em `http://localhost:5401/v1` com a API da OpenAI. Qualquer ferramenta
compatível (Cline, Continue, Aider, Claude Code) pode apontar para lá:

```bash
curl -s localhost:5401/v1/chat/completions -H "Authorization: Bearer $SICOOBITO_API_KEY" -H "content-type: application/json" -d '{"model":"auto/cheap","messages":[{"role":"user","content":"ping"}]}'
```

Estado dos provedores, incluindo o motivo de cada indisponibilidade:

```bash
curl -s localhost:5401/api/health/providers -H "Authorization: Bearer $SICOOBITO_API_KEY"
```

Testes:

```bash
cd apps/api && uv sync --extra azure && uv run pytest
```

### Se alguma porta da faixa estiver ocupada

Altere o mapeamento no `docker-compose.yml`. No Windows com Docker Desktop, a
colisão é traiçoeira: em vez de recusar a conexão, **outro serviço responde no
lugar** — o backend parece no ar mas devolve 404 em todas as rotas.

```bash
netstat -ano | findstr :5401
```

## Configuração

Os modelos e as políticas de roteamento são declarativos:

- `config/providers.yaml` — catálogo de modelos por provedor
- `config/routes.yaml` — perfis (`auto`, `coding`, `cheap`, `fast`, `local-first`)
- `config/pricing.yaml` — preço por 1M tokens, usado na contabilidade

## Estrutura

```
apps/api/src/sicoobito/
  router/     única saída para LLM: catálogo, política, adaptadores, custo
  optimizer/  cache, estimativa de token, compressão, complexidade
  context/    indexação, chunking por símbolo, busca híbrida
  agent/      grafo LangGraph, ferramentas com classe de risco
  workspace/  fs com fronteira, git, github
  sandbox/    container efêmero por sessão
  lsp/        ponte entre o editor e os language servers
  api/        fachada /v1 e rotas de gestão
apps/web/     dashboard e IDE (Next.js + Monaco)
services/executor/  único serviço com acesso ao daemon do Docker (ADR 0002)
config/       providers.yaml, routes.yaml, pricing.yaml
```

## Documentação & Segundo Cérebro

- [Arquitetura](docs/architecture.md) — Visão técnica, fluxo de dados e segurança
- [Decisões Arquiteturais (ADRs)](docs/adr/) — ADRs 0001 a 0005 formais
- **Segundo Cérebro & Knowledge Graph no Obsidian**: [`graphify-out/obsidian/`](graphify-out/obsidian/)
  - Mais de **5.400 notas markdown interligadas** por Wikilinks `[[...]]`.
  - MOCs temáticos (`00 - 🏠 Painel & MOCs/`), Visualizador Canvas e cores por categoria no Graph View.
  - **Como abrir**: No app Obsidian, clique em *"Abrir outro cofre"* → *"Abrir pasta como cofre"* e aponte para `graphify-out/obsidian`.

> [!IMPORTANT]
> **Uso Obrigatório por Agentes de IA:**
> Qualquer agente autônomo (Claude, Gemini, Antigravity ou subagentes) atuando neste repositório **deve obrigatoriamente** consultar o cofre Obsidian (`graphify-out/obsidian/`) e o Grafo de Conhecimento (`graph_search` / `sicoobito.graphify`) antes de planejar e executar modificações estruturais ou de segurança.
