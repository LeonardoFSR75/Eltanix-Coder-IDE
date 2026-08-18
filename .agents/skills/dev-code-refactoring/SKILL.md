---
name: dev-code-refactoring
description: Orienta a refatoração limpa de código, eliminação de código duplicado (DRY) e melhoria de performance mantendo a retrocompatibilidade.
---

# Skill: Refatoração de Código

Skill especializada em melhorar a estrutura interna do código sem alterar seu comportamento externo observável.

## Diretrizes de Refatoração

1. **Inspeção Prévia**:
   - Mapear chamadores da função ou classe antes de alterar assinaturas.
   - Preservar comentários explicativos e docstrings relevantes.
2. **Passos Cirúrgicos**:
   - Fazer alterações pequenas e incrementais.
   - Rodar linter e formatter (`ruff check`, `prettier`) a cada etapa.
3. **Preservação de Contratos**:
   - Garantir que retornos nulos ou exceções esperadas continuem sendo tratados pelos clientes da API.
