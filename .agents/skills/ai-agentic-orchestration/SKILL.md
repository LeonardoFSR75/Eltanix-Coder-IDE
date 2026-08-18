---
name: ai-agentic-orchestration
description: Guia a construção e gerenciamento de fluxos autônomos multiagente (LangGraph), despacho de subagentes e interrupções humanas (Human-in-the-loop).
---

# Skill: Orquestração de Agentes Autônomos

Skill especializada em arquiteturas multiagente, gestão de estado e execução de ferramentas com controle de risco.

## Padrões de Agentes

1. **Classificação de Risco de Ferramentas (`RiskClass`)**:
   - `READ`: Execução automática e transparente.
   - `WRITE` / `EXEC`: Pausa o fluxo (`interrupt()`) exigindo aprovação explícita do usuário.
2. **Ciclo Agêntico**:
   - Mapear intenção -> Executar ferramenta -> Observar resultado -> Reavaliar próximo passo.
3. **Subagentes e Paralelismo**:
   - Delegar sub-tarefas isoladas (ex: pesquisa, auditoria) para subagentes e agregar os resultados no agente principal.
