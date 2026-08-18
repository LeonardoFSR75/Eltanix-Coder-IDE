---
name: dev-fullstack-architecture
description: Orienta o design e construção de arquiteturas Fullstack (FastAPI, Next.js, Svelte 5, Postgres/pgvector, Redis e Docker Compose).
---

# Skill: Arquitetura Fullstack

Skill especializada em definir e implementar padrões de arquitetura sustentáveis para aplicações Web e APIs.

## Princípios Arquiteturais

1. **Separação de Responsabilidades (SOC)**:
   - Backend (`apps/api`): Lógica de negócios, ORM, endpoints REST/gRPC e roteamento de LLM.
   - Frontend (`apps/web` e `apps/desktop`): Interfaces reativas, gerenciamento de estado local e comunicação via HTTP/WebSocket.
2. **Design de APIs**:
   - Respostas padronizadas com tipagem forte (Pydantic / TypeScript interfaces).
   - Versionamento e validação estrita de payload nos middlewares.
3. **Persistência de Dados**:
   - Migrações declarativas (Alembic para Postgres).
   - Suporte a busca vetorial (pgvector) e caching em camadas (Redis).

## Checklists de Implementação

- [ ] Verificar compatibilidade do modelo de dados com schemas existentes.
- [ ] Garantir desacoplamento entre camada de transporte (FastAPI) e serviços de domínio.
- [ ] Validar variáveis de ambiente em `.env.example`.
