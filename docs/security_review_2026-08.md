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

### F-2 — Sem CSRF token; a defesa é 100% `SameSite=Lax` · **Média**
Rotas que mudam estado aceitam o cookie de sessão. `SameSite=Lax` já barra
POST cross-site, então o risco prático é baixo, mas não há segunda linha
(token sincronizador / checagem de `Origin`). Uma navegação top-level `GET`
para uma rota que mudasse estado enviaria o cookie — hoje nenhuma rota de
`auth` muta em `GET`, mas isso não é garantido por lint.
**Recomendação:** (a) trocar o cookie de sessão para `SameSite=Strict` — é
uma IDE, não há fluxo legítimo de navegação cross-site que precise do cookie;
(b) opcional: middleware que exige `Origin`/`Referer` na lista de
`cors_origins` para métodos não-seguros com cookie.

### F-3 — `CORS_ORIGINS` não rejeita `*` com `allow_credentials=True` · **Média**
`_split_origins` aceita qualquer string. Um `.env` com `CORS_ORIGINS=*` (ou
uma origem pública) combinado com `allow_credentials=True` abre a API
autenticada para qualquer site. O default é seguro (localhost), o risco é
operacional.
**Recomendação:** no `field_validator`, recusar `*` e qualquer origem sem
esquema explícito quando credenciais estão habilitadas; logar um aviso alto
se a lista contiver origem não-loopback.

### F-4 — Rate limit de login é só por IP, sem lockout de conta · **Média**
5/min por IP. Um host rotacionando origem (ou rede com NAT) não é contido, e
não há trava por conta nem backoff exponencial. Para local-first o impacto é
menor, e o F-1 (MFA) reduz muito o valor de um brute-force.
**Recomendação:** adicionar contador por *username* (ex. 10 falhas / 15 min →
espera crescente), independente do contador por IP.

### F-5 — Sessões ativas invisíveis e não revogáveis individualmente · **Média**
O usuário não consegue listar "onde estou logado" nem matar uma sessão
específica; só `change-password` (revoga todas) ou esperar o TTL. `AuthSession`
já guarda `user_agent` e `last_seen_at` — falta só expor.
**Recomendação:** `GET /api/auth/sessions` (lista, marca a atual) +
`DELETE /api/auth/sessions/{id}` (revoga uma), com UI em `/profile`.

### F-6 — Eventos de auth não vão para o `audit_log` · **Média**
Login, logout, troca de senha, criação de usuário, enroll/disable de MFA só
aparecem em `structlog`. `AuditLogEntry` existe e é o lugar natural para
trilha consultável.
**Recomendação:** gravar `AuditLogEntry` em login OK/falho (sem senha),
`change_password`, `create_user`, e nos eventos de MFA desta entrega.

### F-7 — Segredo TOTP guardado em claro na coluna · **Baixa** · *anotado*
`user_mfa.secret` (base32) fica em claro, como a maioria das apps sem
envelope-encryption faz. Se o Postgres vazar, o atacante que *também* tem a
senha do usuário passa no 2º fator. O `password_hash` no mesmo vazamento já
permite ataque offline, então o TOTP em claro não é o elo mais fraco.
**Recomendação (opcional):** cifrar `secret` e `recovery_codes` com AES-GCM
usando chave de `ELTANIX_MFA_SECRET_KEY` (env) — exige a dependência
`cryptography`. Sem ela, manter em claro é aceitável para o modelo local-first
e está documentado aqui.

### F-8 — `min_length=6` para senha · **Baixa** · *corrigido nesta entrega*
`CreateUserRequest.password`, `ChangePasswordRequest.new_password` e o form de
`/profile` subiram para `min_length=8`. Checagem de lista de vazadas continua
fora de escopo para um app local.

### F-9 — `ELTANIX_API_KEY`: segredo único, estático, poder total · **Baixa**
Bypass de tudo (RBAC inclusive), sem rotação, sem escopo. É o desenho do
ADR 0005 (canal de serviço), e a comparação é constante-tempo.
**Recomendação:** `.env.example` deve gerar uma chave longa aleatória por
padrão (não um literal como `eltanix-local-dev-key`) e o startup já avisa
quando ela está vazia — manter esse aviso alto.

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

- **F-1** — TOTP + recovery codes + login em 2 etapas (detalhes acima).
- **F-8** — senha mínima 8.
- Rota `/login/mfa` adicionada ao allowlist do meta-teste `test_route_auth_invariant`
  (é a 2ª etapa do login, não pode exigir sessão).

## Acompanhamento (não bloqueia esta entrega)

F-2 (`SameSite=Strict` + checagem de `Origin`), F-3 (recusar `*` em
`CORS_ORIGINS` com credenciais), F-4 (rate limit por username), F-5
(`GET/DELETE /api/auth/sessions`), F-6 (`AuditLogEntry` nos eventos de auth),
F-9 (chave de serviço aleatória por padrão). Cada um cabe num PR pequeno.
