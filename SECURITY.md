# Política de Segurança

## Reportando uma vulnerabilidade

Este projeto lida com execução de comandos, credenciais de provedores de LLM e acesso a
repositórios de código — leve vulnerabilidades a sério.

**Não abra uma issue pública para uma vulnerabilidade de segurança.** Em vez disso, use o
recurso de aviso de segurança privado do GitHub:

1. Vá até a aba **Security** deste repositório.
2. Clique em **Report a vulnerability** (Security Advisories).
3. Descreva a vulnerabilidade, os passos para reproduzi-la e o impacto potencial.

Isso abre uma conversa privada entre você e os mantenedores, sem expor o problema publicamente
antes de haver uma correção disponível.

## O que esperar

- Confirmação de recebimento em até alguns dias úteis.
- Uma avaliação inicial de severidade e, se aplicável, um plano de correção.
- Crédito público (se desejado) depois que a correção for publicada — divulgação coordenada,
  não imediata.

## Escopo

Áreas especialmente sensíveis neste repositório, caso ajude a categorizar o achado:

- **Isolamento de execução** ([ADR 0002](docs/adr/0002-executor-isolado.md)): comandos do
  agente devem sempre passar pelo serviço `executor` isolado — nunca falar direto com o
  daemon Docker da API.
- **Proteção anti-SSRF** ([ADR 0006](docs/adr/0006-integracao-firecrawl-web-rag.md)): toda
  requisição web externa (Firecrawl, navegador interno, deep research) deve ser validada
  contra redes privadas, loopback e metadados de nuvem.
- **Autenticação e sessão** ([ADR 0005](docs/adr/0005-login-obrigatorio.md)): nenhuma rota
  deve ficar acessível sem sessão válida ou API key.
- **Aprovação por classe de risco**: qualquer caminho que permita uma ferramenta `WRITE`/`EXEC`
  executar sem passar pela aprovação humana é uma vulnerabilidade, não uma conveniência.
- **Sanitização de PII e segredos**: vazamento de dados sensíveis do usuário (CPF, e-mail,
  chaves de API) para modelos remotos ou logs.

## Versões suportadas

O projeto ainda está em fase beta — apenas a branch `main` recebe correções de segurança por
enquanto.
