---
name: dev-testing-automation
description: Guia a criação e execução automatizada de suítes de testes (Pytest, Vitest, Playwright), mocking e métricas de cobertura de código.
---

# Skill: Automação de Testes

Skill especializada na escrita, organização e execução de testes automatizados com alta confiabilidade.

## Estratégia de Testes

1. **Testes Unitários**:
   - Testar funções puras, validadores e lógica de domínio em isolamento.
   - Utilizar mocks/stubs para banco de dados e APIs externas.
2. **Testes de Integração**:
   - Validar rotas HTTP da API (FastAPI `TestClient`) contra um banco de testes real ou transacional.
3. **Execução de Comandos**:
   - Backend: `cd apps/api && uv run pytest tests -q`
   - Frontend: `cd apps/web && bun test`

## Regras de Qualidade

- Nunca marcar testes falhos como ignorados sem motivo documentado.
- Garantir que fixtures limpem o estado após cada suite.
