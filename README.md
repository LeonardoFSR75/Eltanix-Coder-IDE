# SicoobitoCode

Plataforma local-first de codificação agêntica: um IDE web estilo VS Code com chat e agente
autônomo sobre o repositório, integração com Git/GitHub e um **gateway multi-modelo** que
roteia entre Ollama (local), Azure AI Foundry e Databricks com contabilidade de custo e
otimização de token.

O princípio que sustenta tudo: **nenhum módulo fala com um provedor de LLM diretamente**.
Toda chamada passa pelo router, e cada provedor entra como adaptador plugável — trocar de
modelo ou de nuvem é mudança de configuração, não de código.

## Estado atual

Fase 1 (gateway + custo) em construção. As fases seguintes estão descritas em `docs/`.

| Fase | Escopo | Status |
|---|---|---|
| 1 | Gateway multi-modelo, fallback, contabilidade de custo, dashboard | em andamento |
| 2 | Indexação do repositório (tree-sitter + pgvector), busca híbrida | planejado |
| 3 | Agente LangGraph, sandbox Docker, Git/GitHub, PRs | planejado |
| 4 | IDE web (Monaco, diff, terminal) | planejado |
| 5 | Otimização avançada de token | planejado |

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

## Configuração

Os modelos e as políticas de roteamento são declarativos:

- `config/providers.yaml` — catálogo de modelos por provedor
- `config/routes.yaml` — perfis (`auto`, `coding`, `cheap`, `fast`, `local-first`)
- `config/pricing.yaml` — preço por 1M tokens, usado na contabilidade

## Documentação

- [Arquitetura](docs/architecture.md)
- [Decisões arquiteturais](docs/adr/)
