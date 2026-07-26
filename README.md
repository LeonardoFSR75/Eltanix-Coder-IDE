# SicoobitoCode

Plataforma local-first de codificação agêntica: um IDE web estilo VS Code com chat e agente
autônomo sobre o repositório, integração com Git/GitHub e um **gateway multi-modelo** que
roteia entre Ollama (local), Azure AI Foundry e Databricks com contabilidade de custo e
otimização de token.

O princípio que sustenta tudo: **nenhum módulo fala com um provedor de LLM diretamente**.
Toda chamada passa pelo router, e cada provedor entra como adaptador plugável — trocar de
modelo ou de nuvem é mudança de configuração, não de código.

## Estado atual

As cinco fases estão construídas e **validadas contra infraestrutura real** —
Postgres com pgvector, Redis e Docker no ar.

| Fase | Escopo | Status |
|---|---|---|
| 1 | Gateway multi-modelo, fallback, contabilidade de custo, dashboard | validada |
| 2 | Indexação do repositório (tree-sitter + pgvector), busca híbrida | validada |
| 3 | Agente LangGraph, sandbox Docker, Git/GitHub, PRs | validada |
| 4 | IDE web (Monaco, explorer, busca, Git, terminal, palette) | validada |
| 5 | Compressão de contexto e roteamento por complexidade | construída |

Exercitado de ponta a ponta: as três migrações contra Postgres real (extensão
`vector`, índice HNSW, `tsvector` como coluna gerada); indexação deste próprio
repositório (117 arquivos, 849 chunks); sessão de agente com worktree Git e
sandbox Docker, confirmando na prática usuário não-root, escrita barrada fora do
workspace e rede desabilitada; e o dashboard renderizando telemetria real.

Falta apenas uma chamada a um modelo de verdade — depende do Ollama ou de
credenciais de nuvem.

186 testes (~107s). Ruff, `tsc` e `next build` limpos.

## Requisitos

- **Docker** — é o único requisito de execução; toda a stack roda em containers
- Ollama no host, opcional mas recomendado: é a base da política `local-first`
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

```bash
docker compose up -d --build
```

```bash
docker compose exec api alembic upgrade head
```

Pronto:

| Serviço | Porta | URL |
|---|---|---|
| IDE e dashboard | 5400 | http://localhost:5400/ide |
| API (gateway OpenAI-compatible) | 5401 | http://localhost:5401/v1 |
| Executor (interno) | 5402 | — |
| Postgres | 5403 | — |
| Redis | 5404 | — |

A faixa 5400–5499 foi escolhida para não disputar 3000, 8000 e 5432 com outros
projetos.

Modelo local — sem ele o perfil `local-first` não tem para onde ir e a
indexação fica sem embeddings:

```bash
ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text
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
  api/        fachada /v1 e rotas de gestão
apps/web/     dashboard e IDE (Next.js + Monaco)
services/executor/  único serviço com acesso ao daemon do Docker (ADR 0002)
config/       providers.yaml, routes.yaml, pricing.yaml
```

## Documentação

- [Arquitetura](docs/architecture.md)
- [Decisões arquiteturais](docs/adr/)
- Notas de projeto no Obsidian: `vault-solo/Projects/sicoobito-code/`
