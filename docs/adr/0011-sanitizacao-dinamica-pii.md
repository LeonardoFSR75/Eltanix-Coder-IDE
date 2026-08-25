# ADR 0011 — Sanitização Dinâmica de Prompts e Mascaramento PII (Redaction)

**Status:** aceito · **Data:** 2026-08-19

## Contexto

Ao utilizar provedores de LLM hospedados em nuvem pública (como OpenAI, Anthropic, Groq ou Azure AI Foundry), existe o risco de envio acidental de informações de identificação pessoal (*PII - Personally Identifiable Information*) como CPFs, e-mails, números de cartão de crédito e tokens de API contidos no código-fonte ou em logs do workspace.

Para atender aos requisitos corporativos de privacidade (LGPD / GDPR) e prevenir o vazamento de credenciais em APIs externas, é necessário um mecanismo centralizado de sanitização preventiva de dados sensíveis.

## Decisão

1. **Sanitização Preventiva no Gateway (`PIIRedactor`)**:
   - Todo texto de prompt direcionado a provedores de LLM remotos passa obrigatoriamente pelo sanitizador `eltanix.security.pii_redactor.PIIRedactor`.
   - O sanitizador substitui padrões sensíveis detectados por marcadores genéricos seguros:
     - CPFs `000.000.000-00` ──► `[REDACTED_CPF]`
     - E-mails `usuario@dominio.com` ──► `[REDACTED_EMAIL]`
     - Cartões de crédito ──► `[REDACTED_CARD]`
     - Chaves de API / Tokens ──► `[REDACTED_API_KEY]`

2. **Modelos Locais Isentos de Redaction**:
   - Chamadas direcionadas a modelos locais (ex: Ollama rodando no próprio container/host) são isentas de mascaramento por padrão, garantindo que o contexto original completo permaneça intacto para processamento privado.

## Alternativas consideradas

- **Confiar apenas no usuário para não colar dados sensíveis** — Propenso a falhas humanas acidentais em logs de depuração ou código legado. Rejeitado.
- **Mascarar prompts também em modelos locais (Ollama)** — Prejudica o desempenho da IA em ambientes 100% privados sem nenhum ganho de privacidade real, visto que os dados não saem do servidor local. Rejeitado.

## Consequências

- Conformidade com LGPD/GDPR para integração de provedores SaaS de IA.
- Prevenção ativa contra o vazamento de segredos e credenciais em APIs externas.
