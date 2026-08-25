# Coleção Bruno — NovaAI Studio API

Abra esta pasta (`apps/api/bruno`) como coleção no [Bruno](https://www.usebruno.com/).

## Configurar

1. Selecione o ambiente **local** (canto superior direito do Bruno).
2. Preencha `apiKey` com o valor de `NOVAAI_STUDIO_API_KEY` do seu `.env` — é o
   mesmo canal de serviço que CI/cline/continue/aider/cursor usam (ver
   `docs/adr/0005-login-obrigatorio.md`), não a sessão de usuário do browser.
3. Se a API estiver rodando fora do `docker compose` padrão, ajuste `baseUrl`.

## Pastas

- **auth/** — login por usuário/senha, cookie de sessão (`sessionToken`).
  Rode "Login" primeiro; as outras requests desta pasta usam o cookie
  automaticamente.
- **agent/** — ciclo de vida de uma sessão do agente: criar, rodar, aprovar
  ação WRITE/EXEC pendente, ver diff, aceitar/rejeitar arquivo, fechar. Rode
  "Create Session" primeiro para preencher `sessionId`.

`vars:post-response` em cada request já captura `session_id`/`token` da
resposta para a próxima chamada — não precisa copiar/colar na mão.
