---
name: browser-testing-e2e-playwright
description: Diretrizes de testes de ponta a ponta e automação de interface no navegador integrado Playwright do ecossistema Eltanix Coder IDE.
---

# Browser Testing & E2E Verification Guide

Este guia orienta o agente na validação visual, funcional e ponta a ponta de aplicações Web em execução no ambiente de desenvolvimento do Eltanix Coder IDE.

---

## 1. Fluxo de Validação de Interface

Quando uma aplicação web estiver rodando no sandbox:
1. **Navegação Inicial**:
   - Chame `browser_action(action="navigate", url="http://localhost:<porta>")`.
   - Obtenha o snapshot do DOM via `action="content"`.

2. **Interações de Formulário & Cliques**:
   - `action="type", selector="input[name='nome']", text="Valor de Teste"`
   - `action="click", selector="button[type='submit']"`

3. **Asserção de Resposta & Inspeção de Erros**:
   - Verifique o texto renderizado na tela (`content`) para confirmar que a resposta ou mensagem de sucesso apareceu.
   - Use `action="console_logs"` para inspecionar erros JavaScript ou chamadas de API quebradas.
   - Use `action="screenshot"` para capturar o estado visual renderizado.

---

## 2. Boas Práticas
- Não tente acessar domínios públicos da internet (o sandbox e o browser rodam na rede interna isolada `eltanix_browser_net`).
- Sempre teste formulários e fluxos principais após criar ou alterar componentes frontend.
