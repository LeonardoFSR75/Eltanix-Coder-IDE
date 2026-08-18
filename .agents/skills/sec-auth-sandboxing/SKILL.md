---
name: sec-auth-sandboxing
description: Orienta a implementação de autenticação robusta (JWT/Cookies HttpOnly), isolamento em sandbox de executores e mitigação anti-SSRF.
---

# Skill: Autenticação & Sandboxing

Skill dedicada a isolar a execução de código arbitrário e proteger mecanismos de acesso.

## Práticas de Sandboxing e SSRF

1. **Proteção Anti-SSRF**:
   - Validar URLs alvo com `validate_target_url()` antes de requisições de scrape/web.
   - Bloquear requisições para IPs privados (RFC 1918), `localhost` (127.0.0.1) e metadados de nuvem.
2. **Execução Segura de Comandos**:
   - Submeter execução de código de terceiros exclusivamente em containers isolados (`executor`).
   - Bloquear permissões de root (`cap_drop: ALL`) e acesso à rede interna no sandbox.
3. **Sessões e Cookies**:
   - Definir `HttpOnly`, `SameSite=Lax` ou `Strict`, e `Secure` em cookies de autenticação.
