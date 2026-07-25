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
| 4 | IDE web (Monaco, diff, agente, terminal) | validada |
| 5 | Compressão de contexto e roteamento por complexidade | construída |

Exercitado de ponta a ponta: as três migrações contra Postgres real (extensão
`vector`, índice HNSW, `tsvector` como coluna gerada); indexação deste próprio
repositório (117 arquivos, 849 chunks); sessão de agente com worktree Git e
sandbox Docker, confirmando na prática usuário não-root, escrita barrada fora do
workspace e rede desabilitada; e o dashboard renderizando telemetria real.

Falta apenas uma chamada a um modelo de verdade — depende do Ollama ou de
credenciais de nuvem.

172 testes (~74s). Ruff, `tsc` e `next build` limpos.

## Requisitos

- Docker (Postgres + Redis)
- Python 3.12 (gerenciado pelo `uv`)
- Node 20+ (para o dashboard)
- Ollama, opcional mas recomendado — é a base da política `local-first`

## Início rápido

Copie o `.env` e defina uma chave (`python -c "import secrets;print(secrets.token_urlsafe(32))"`):

```bash
cp .env.example .env
```

Suba a infraestrutura:

```bash
docker compose up -d postgres redis
```

Backend (a primeira execução instala o Python 3.12 pelo `uv`):

```bash
cd apps/api && uv sync --extra azure && uv run alembic upgrade head
```

```bash
cd apps/api && uv run uvicorn sicoobito.main:app --reload --port 8000
```

Modelo local — sem isto, o perfil `local-first` não tem para onde ir:

```bash
ollama pull qwen2.5-coder:7b
```

Dashboard:

```bash
cd apps/web && npm install && npm run dev
```

O gateway responde em `http://localhost:8000/v1` com a API da OpenAI. Qualquer ferramenta
compatível (Cline, Continue, Aider, Claude Code) pode apontar para lá:

```bash
curl -s localhost:8000/v1/chat/completions -H "Authorization: Bearer $SICOOBITO_API_KEY" -H "content-type: application/json" -d '{"model":"auto/cheap","messages":[{"role":"user","content":"ping"}]}'
```

Estado dos provedores, incluindo o motivo de cada indisponibilidade:

```bash
curl -s localhost:8000/api/health/providers -H "Authorization: Bearer $SICOOBITO_API_KEY"
```

Testes:

```bash
cd apps/api && uv run pytest
```

### Se as portas 8000 ou 3000 estiverem ocupadas

No Windows com Docker Desktop, o proxy do WSL costuma reservar essas portas para
containers de outros projetos. A colisão é traiçoeira: em vez de recusar a
conexão, **outro serviço responde no lugar deste** — o backend parece no ar mas
devolve 404 em todas as rotas.

Para conferir quem está na porta:

```bash
netstat -ano | findstr :8000
```

Backend em outra porta:

```bash
cd apps/api && uv run uvicorn sicoobito.main:app --host 127.0.0.1 --port 8010
```

Front em outra porta: defina `PORT=3010` no `apps/web/.env.local`, junto com
`SICOOBITO_API_URL` apontando para o backend.

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
config/       providers.yaml, routes.yaml, pricing.yaml
```

## Documentação

- [Arquitetura](docs/architecture.md)
- [Decisões arquiteturais](docs/adr/)
- Notas de projeto no Obsidian: `vault-solo/Projects/sicoobito-code/`
