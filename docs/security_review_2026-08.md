# Revisão de Segurança — Superfície de Autenticação e Sessão

**Data:** 2026-08-29 · **Escopo:** `apps/api/src/eltanix/auth/`, `api/deps.py`,
`api/routes/auth.py`, `api/middleware.py`, `api/errors.py`, proxy do Next
(`apps/web/app/api/gateway`, `apps/web/app/api/session`), config de CORS/cookie.
Fora de escopo: sandbox do agente (ADR 0002), SSRF (revisado no Lote 2), MCP
scanner (ADR 0010).

Legenda de severidade: **Alta** (corrigir já) · **Média** (planejar) ·
**Baixa** (aceitável / anotar) · **OK** (defesa presente e correta).

---

## O que está sólido

| Área | Avaliação |
|---|---|
| Hash de senha | `scrypt` N=2¹⁶ com parâmetros embutidos no hash (`n$r$p$salt$hash`), re-hash transparente ao subir custo, formato legado ainda verificável. **OK** |
| Token de sessão | 256 bits (`secrets.token_urlsafe(32)`), só o `sha256` no banco, comparação com `hmac.compare_digest`, TTL 14 dias, nunca volta ao cliente depois do login. **OK** |
| Timing de login | `_DUMMY_PASSWORD_HASH` roda `scrypt` mesmo com usuário inexistente — fecha o canal de enumeração de usuário por latência. **OK** |
| Rate limit de login | `INCR`+`expire` atômico (Redis) ou lista em memória sem `await` no meio — corrige a corrida de "várias tentativas leem a mesma contagem". 5/min por IP. **OK** (ver F-4) |
| `_client_ip` | Ignora `X-Forwarded-For` de propósito (não há proxy confiável na frente) — impede reset do próprio rate limit trocando o header. **OK** |
| `validate_session` | Fail-closed: qualquer exceção → `None`; confere `revoked_at`, `expires_at`, `is_active`. **OK** |
| `require_session` (ADR 0005) | Nunca abre por omissão — sem credencial válida é sempre 401. Chave de serviço via `hmac.compare_digest`. **OK** |
| `change_password` | Revoga todas as outras sessões do usuário (token vazado morre junto). **OK** |
| Cookie de sessão | `HttpOnly`, `SameSite=Lax`, `Secure` em produção; token nunca chega ao JS do browser (só o Route Handler do Next o manipula). **OK** |
| Handler de exceção | `api/errors.py` devolve mensagem genérica + `request_id`, sem stack. **OK** |

---

## Achados

### F-1 — Fator único para sessão de browser · **Alta** · *corrigido nesta entrega*
Até agora, senha era o único fator. Um vazamento de senha (phishing, reuso,
keylogger) dava acesso total. **Ação:** TOTP (RFC 6238) + códigos de
recuperação, login em 2 etapas. Implementado em `auth/totp.py`,
`auth/service.py`, `api/routes/auth.py`, tabela `user_mfa`
(migração `0027_user_mfa.py`).

### F-2 — Sem CSRF token; a defesa é 100% `SameSite=Lax` · **Média** · *corrigido nesta entrega*
Rotas que mudam estado aceitam o cookie de sessão. `SameSite=Lax` já barra
POST cross-site, então o risco prático é baixo, mas não há segunda linha
(token sincronizador / checagem de `Origin`). Uma navegação top-level `GET`
para uma rota que mudasse estado enviaria o cookie — hoje nenhuma rota de
`auth` muta em `GET`, mas isso não é garantido por lint.
**Recomendação:** (a) trocar o cookie de sessão para `SameSite=Strict` — é
uma IDE, não há fluxo legítimo de navegação cross-site que precise do cookie;
(b) opcional: middleware que exige `Origin`/`Referer` na lista de
`cors_origins` para métodos não-seguros com cookie.
**Feito:** cookie de sessão agora é `SameSite=Strict` nos dois handlers de
`app/api/session` (login direto e 2ª etapa MFA); o proxy `app/api/gateway`
recusa (403) método não-seguro cujo header `Origin` não bate com o host do
próprio gateway.

### F-3 — `CORS_ORIGINS` não rejeita `*` com `allow_credentials=True` · **Média** · *corrigido nesta entrega*
`_split_origins` aceita qualquer string. Um `.env` com `CORS_ORIGINS=*` (ou
uma origem pública) combinado com `allow_credentials=True` abre a API
autenticada para qualquer site. O default é seguro (localhost), o risco é
operacional.
**Recomendação:** no `field_validator`, recusar `*` e qualquer origem sem
esquema explícito quando credenciais estão habilitadas; logar um aviso alto
se a lista contiver origem não-loopback.
**Feito:** `Settings._sanitize_origins` (`config.py`, `field_validator` after)
descarta `""` e `"*"` (com `warnings.warn` neste último) e emite aviso alto
para toda origem não-loopback, mantendo-a na lista.

### F-4 — Rate limit de login é só por IP, sem lockout de conta · **Média** · *corrigido nesta entrega*
5/min por IP. Um host rotacionando origem (ou rede com NAT) não é contido, e
não há trava por conta nem backoff exponencial. Para local-first o impacto é
menor, e o F-1 (MFA) reduz muito o valor de um brute-force.
**Recomendação:** adicionar contador por *username* (ex. 10 falhas / 15 min →
espera crescente), independente do contador por IP.
**Feito:** `AuthService.check_and_register_user_attempt` — 10 tentativas /
15 min por username (case-insensitive, truncado em 64 chars), mesmo idioma
atômico `INCR`+`expire` no Redis com fallback em memória. `login` barra (429)
se o contador por IP **ou** por username estourar; sucesso zera o contador
por username via `reset_user_attempts`.

### F-5 — Sessões ativas invisíveis e não revogáveis individualmente · **Média** · *corrigido nesta entrega*
O usuário não consegue listar "onde estou logado" nem matar uma sessão
específica; só `change-password` (revoga todas) ou esperar o TTL. `AuthSession`
já guarda `user_agent` e `last_seen_at` — falta só expor.
**Recomendação:** `GET /api/auth/sessions` (lista, marca a atual) +
`DELETE /api/auth/sessions/{id}` (revoga uma), com UI em `/profile`.
**Feito:** `GET /api/auth/sessions` (marca `current` pelo hash do cookie) e
`DELETE /api/auth/sessions/{session_id}` (escopo `WHERE user_id` — não dá
para matar sessão alheia por id; 404 se não existir/já revogada). Store:
`list_active_sessions_for_user` / `revoke_session_by_id`. UI: painel
`SessionsPanel` em `/profile`. Round-trip contra `user_mfa`/`auth_session`
no Postgres fica sob `pg_session` (pulado sem `DATABASE_URL_TEST`).

### F-6 — Eventos de auth não vão para o `audit_log` · **Média** · *corrigido nesta entrega*
Login, logout, troca de senha, criação de usuário, enroll/disable de MFA só
aparecem em `structlog`. `AuditLogEntry` existe e é o lugar natural para
trilha consultável.
**Recomendação:** gravar `AuditLogEntry` em login OK/falho (sem senha),
`change_password`, `create_user`, e nos eventos de MFA desta entrega.
**Feito:** helper `_audit()` em `api/routes/auth.py` (best-effort, nunca
fatal, só grava IP + módulo `auth` sem senha) em login OK/falho, login MFA
OK/falho, logout, `change_password` OK/falho, `create_user`,
`session.revoke`, `mfa.activate`, `mfa.disable` OK/falho.

### F-7 — Segredo TOTP guardado em claro na coluna · **Baixa** · *corrigido nesta entrega*
`user_mfa.secret` (base32) ficava em claro. Se o Postgres vazar, o atacante que
*também* tem a senha do usuário passa no 2º fator.
**Feito:** `auth/secret_box.py` (`SecretBox`) cifra o segredo com **AES-256-GCM**
quando `ELTANIX_MFA_SECRET_KEY` está definida — chave derivada por `scrypt`
determinístico, envelope `enc:v1:` + base64(nonce+ct+tag), coluna alargada para
`String(255)` (migração `0028`). Sem a env var, o valor fica em claro **como
antes** (degrada, não quebra — F-7 é *Baixa* e o modelo é local-first); o
startup (`main.py`) emite `auth.mfa.secret_key_missing` em nível `warning` se
houver linha em `user_mfa` sem a chave. Segredo em claro pré-F-7 é regravado
cifrado na primeira autenticação bem-sucedida (`_verify_second_factor` →
`store.set_mfa_secret`), mesmo padrão do re-hash de senha. `recovery_codes`
ficam fora: já são `sha256` de uso único (não recuperáveis), cifrá-los é
ganho marginal e invadiria o `store` inteiro — deferido.
Dependência nova: `cryptography` (wheel `abi3` pré-compilada, sem toolchain —
mesmo critério de `psycopg[binary]`, não recai no veto a bcrypt/argon2 do
ADR 0005). Testes: `tests/test_secret_box.py` + wiring em `tests/test_mfa.py`.

### F-8 — `min_length=6` para senha · **Baixa** · *corrigido nesta entrega*
`CreateUserRequest.password`, `ChangePasswordRequest.new_password` e o form de
`/profile` subiram para `min_length=8`. Checagem de lista de vazadas continua
fora de escopo para um app local.

### F-9 — `ELTANIX_API_KEY`: segredo único, estático, poder total · **Baixa** · *mitigado nesta entrega*
Bypass de tudo (RBAC inclusive), sem rotação, sem escopo. É o desenho do
ADR 0005 (canal de serviço), e a comparação é constante-tempo.
**Feito:** bloco Núcleo do `.env.example` reescrito — instrução única no topo
para gerar valor aleatório para **cada** segredo (`token_urlsafe(32)`),
placeholder `troque-me` mantido só como marcador inválido, e a chave descrita
como raiz sem rotação. O startup (`main.py:106`) já aborta com
`ELTANIX_API_KEY` vazia — aviso preservado. Rotação/escopo real fica fora:
mudaria o contrato do ADR 0005.

### F-10 — Proxy do Next repassa `Authorization` do cliente · **Baixa**
`app/api/gateway` encaminha o header `Authorization`/`x-api-key` que o
browser mandar. O JS do bundle nunca tem a chave, então só um XSS no app web
conseguiria injetá-la — e um XSS já é game over. Sem ação; anotado como
premissa (o app web tem que continuar livre de XSS: nada de `dangerouslySet…`
com dado de usuário, CSP no futuro).

---

## O que a entrega de MFA adiciona

- Tabela `user_mfa` (1:1 com `app_user`) — ausência de linha = "MFA não
  configurado", nada muda para quem não ativou.
- `auth/totp.py`: RFC 6238 puro stdlib (`hmac`/`hashlib`/`struct`), janela de
  ±1 passo (30s), sem dependência nativa. QR via `segno` (Python puro).
- Login em 2 etapas: `POST /api/auth/login` com MFA ativo devolve
  `{"mfa_required": true, "mfa_token": …}` (desafio opaco, 5 min, uso único,
  em memória — single-instance) **sem criar sessão**; `POST /api/auth/login/mfa`
  troca `mfa_token` + código (TOTP ou recuperação) pela sessão.
- Enrollment autenticado: `setup` (gera segredo, `enabled=False`) → `activate`
  (confere 1º código, `enabled=True`, entrega 10 códigos de recuperação uma
  única vez) → `disable` (senha + código).
- Códigos de recuperação: 10, `sha256` no banco (alta entropia, mesmo
  critério do token de sessão), uso único por remoção.
- `change_password` continua revogando sessões; adicionalmente, ativar/desativar
  MFA revoga as outras sessões.

## Entregue neste PR

Primeira leva (Lote 7):

- **F-1** — TOTP + recovery codes + login em 2 etapas (detalhes acima).
- **F-8** — senha mínima 8.
- Rota `/login/mfa` adicionada ao allowlist do meta-teste `test_route_auth_invariant`
  (é a 2ª etapa do login, não pode exigir sessão).

Segunda leva (Lote 8 — follow-ups de severidade Média):

- **F-2** — cookie de sessão `SameSite=Strict`; checagem de `Origin` para
  métodos não-seguros no proxy `app/api/gateway`.
- **F-3** — `Settings._sanitize_origins` descarta `*`/`""` e avisa alto para
  origem não-loopback.
- **F-4** — rate limit por username (10 falhas / 15 min), somado ao por IP.
- **F-5** — `GET /api/auth/sessions` + `DELETE /api/auth/sessions/{id}` com
  painel em `/profile`.
- **F-6** — `AuditLogEntry` (via helper `_audit`) em todos os eventos de auth.
- Testes: `tests/test_auth_hardening.py` (F-3, F-4) e novos casos em
  `tests/test_mfa.py` (endpoints de sessão exigem autenticação).

Terceira leva (Lote 9 — cauda de severidade Baixa, item C2 do roadmap ponta a ponta):

- **F-7** — `auth/secret_box.py` (AES-256-GCM), config `ELTANIX_MFA_SECRET_KEY`,
  migração `0028` (coluna `secret` → 255), aviso de boot, migração preguiçosa
  do segredo em claro. `tests/test_secret_box.py` + wiring em `tests/test_mfa.py`.
- **F-9** — bloco Núcleo do `.env.example` reescrito.

## Acompanhamento (não bloqueia esta entrega)

- **F-7 / `recovery_codes`** — deixados em claro-hash (`sha256`): já são de uso
  único e não recuperáveis; cifrar exigiria decifrar a lista inteira a cada
  leitura e invadir `store.py` — ganho marginal, deferido.
- **F-5 (parte de banco)** — `list_active_sessions_for_user` /
  `revoke_session_by_id` só têm cobertura sob `pg_session` (requer
  `DATABASE_URL_TEST`); vale um `tests/test_auth.py` dedicado quando o CI
  ganhar um Postgres.
