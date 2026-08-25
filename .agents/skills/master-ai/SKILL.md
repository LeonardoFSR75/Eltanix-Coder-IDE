---
name: master-ai
description: Skill Mestra para Inteligência Artificial e LLMs. Coordena arquitetura de RAG, engenharia de prompts e orquestração de subagentes autônomos.
---

# Master Skill: Inteligência Artificial (AI Hub)

Esta skill mestra gerencia o ciclo de vida de soluções baseadas em Modelos de Linguagem (LLMs), RAG (Retrieval-Augmented Generation) e Agentes Autônomos.

## Skills Especializadas da Ramificação

- [`ai-prompt-rag-engineering`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/.agents/skills/ai-prompt-rag-engineering/SKILL.md): Engenharia de prompts, pipelines de RAG vetorial/grafo (pgvector, Graphify), busca híbrida e estratégias de re-ranking.
- [`ai-agentic-orchestration`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/.agents/skills/ai-agentic-orchestration/SKILL.md): Orquestração de grafos de decisão com LangGraph, despacho de subagentes, controle de fluxo e tratamento de chamadas de ferramentas (MCP/Tools).

## Princípios de Integração de IA

1. **Camada Única de Roteamento**: Centralizar requisições a LLMs em uma única fachada/router (`novaai_studio.router`).
2. **Contexto Relevante e Denso**: Maximizar a precisão da recuperação antes de injetar informações no prompt.
3. **Resiliência e Fallback**: Prever timeouts, rate limits e fallback transparente entre provedores de modelos.
