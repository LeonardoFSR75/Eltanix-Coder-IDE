---
name: ai-prompt-rag-engineering
description: Orienta a criação de pipelines RAG (dense vector + knowledge graph), chunking inteligente, geração de embeddings e otimização de prompts.
---

# Skill: Engenharia de Prompt & RAG

Skill especializada na construção de sistemas de recuperação de informação de alta fidelidade para LLMs.

## Arquitetura RAG Híbrida

1. **Recuperação Vetorial (Dense Retrieval)**:
   - Chunking semântico respeitando limites de código ou parágrafos.
   - Indexação vetorial com HNSW em Postgres (`pgvector`).
2. **Conhecimento em Grafo (Graph RAG)**:
   - Extração de entidades e relacionamentos via Graphify.
   - Navegação em $N$-hops para mapeamento de dependências no Obsidian / Segundo Cérebro.
3. **Engenharia de Prompt**:
   - Instruções de sistema claras, sem ambiguidades.
   - Uso de tags estruturadas (ex: `<USER_REQUEST>`, `<CONTEXT>`).
   - Saídas estruturadas via JSON Schema ou Pydantic.
