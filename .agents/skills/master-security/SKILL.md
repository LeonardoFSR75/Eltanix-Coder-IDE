---
name: master-security
description: Skill Mestra para Segurança da Informação. Coordena auditorias SAST/DAST, conformidade OWASP, controle de permissões e mitigação de vulnerabilidades.
---

# Master Skill: Segurança (Security Hub)

Esta skill mestra gerencia o ciclo de segurança ofensiva e defensiva do software, prevenindo vazamentos de dados, execução indevida e falhas de autenticação.

## Skills Especializadas da Ramificação

- [`sec-vulnerability-audit`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/.agents/skills/sec-vulnerability-audit/SKILL.md): Auditoria estática de código (SAST), análise de vulnerabilidades OWASP Top 10 e higienização de dependências.
- [`sec-auth-sandboxing`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/.agents/skills/sec-auth-sandboxing/SKILL.md): Isolamento de execução (sandbox), proteção anti-SSRF, controle de tokens e sessões seguras.

## Diretrizes Fundamentais de Segurança

1. **Validação Estrita de Input**: Nunca confiar em dados vindos de requisições externas.
2. **Princípio do Menor Privilégio**: Processos de segundo plano e containers de execução devem rodar não-root e com permissões mínimas.
3. **Gestão de Segredos**: Nunca expor API keys, senhas ou tokens em arquivos rastreados pelo git.
