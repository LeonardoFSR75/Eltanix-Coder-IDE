# ADR 0005 — Login obrigatório com sessão por cookie, API key vira canal de serviço

**Status:** aceito · **Data:** 2026-08-08

## Contexto

Até aqui a fronteira de segurança real era a combinação "porta publicada só em
`127.0.0.1`" + `NOVAAI_STUDIO_API_KEY` compartilhada (`api/deps.py::require_api_key`),
documentada na seção "Segurança" do `CLAUDE.md` raiz: sem a chave definida, a
API ficava aberta a qualquer chamada local. Isso fazia sentido enquanto o
único consumidor do browser era o próprio operador na própria máquina — o
gateway do Next (`apps/web/app/api/gateway/[...path]/route.ts`) injetava a
chave no servidor e o browser nunca via nada.

O modelo não tem conta de usuário: uma chave, um "dono" implícito. Não dá
para saber quem fez o quê, não dá para revogar acesso de uma sessão específica
sem trocar a chave para todo mundo, e não tem como o produto crescer para
"mais de uma pessoa usa esta instância" sem primeiro ter identidade de
usuário — que é exatamente o problema que login resolve.

## Decisão

**Login vira obrigatório para o browser; a API key vira um canal de serviço
separado.** Duas credenciais válidas, dois propósitos:

- `AppUser` + `AuthSession` (`db/models.py`) — conta de usuário real: senha em
  `scrypt` (stdlib, `auth/service.py::_hash_password`, evita puxar uma
  dependência com wheel nativo em ambiente Windows sem MSVC Build Tools),
  token de sessão opaco em cookie `httpOnly`, só o hash SHA-256 do token
  persiste no banco (`_hash_token`) — mesmo padrão que `hmac.compare_digest`
  já usava para a API key de serviço.
- `NOVAAI_STUDIO_API_KEY` continua existindo e validando por `hmac.compare_digest`,
  mas passa a ser o canal para ferramenta externa server-to-server (CI, cline,
  continue, aider, cursor) — o gateway do Next **parou de reencaminhar a API
  key automaticamente** para chamadas vindas do browser do usuário.

**`require_session` (`api/deps.py`) substitui `require_api_key` como `AuthDep`
em toda rota.** A diferença de comportamento é o ponto central desta decisão:
`require_api_key` ainda existe no código (nada o chama mais), e continua
aberto por omissão sem chave configurada — mas não é mais o guard efetivo.
`require_session` aceita API key válida OU cookie de sessão válido, e **nunca
fica aberto por omissão**: sem nenhuma das duas, 401 sempre. É essa mudança —
não a existência da tabela de usuários por si — que torna login obrigatório
na prática.

**Etapa 1 de um plano em duas etapas, documentado no próprio código
(`auth/service.py` docstring): um único usuário seed, sem RBAC.**
`ensure_seed_user` roda no lifespan (`main.py`) e é idempotente — não faz
nada se `app_user` já tem alguém. Sem `NOVAAI_STUDIO_ADMIN_PASSWORD` no `.env`,
gera uma senha aleatória e loga em nível `info` com a dica explícita para o
operador fixar a variável (`main.py:166-181`) — visível nos logs do primeiro
`docker compose up`, não escondida.

**Rate limit e troca de senha entram junto** (`auth/service.py::
check_and_register_attempt`): 5 tentativas por IP por minuto, Redis
`INCR`+`EXPIRE` atômico com fallback em lista de memória quando Redis está
fora — degrada, não quebra, mesmo princípio do resto da plataforma. Troca de
senha (`change_password`) revoga toda outra sessão ativa do usuário — um
token de sessão vazado para de valer no momento em que o dono legítimo troca
a senha.

## Consequências

- **`CLAUDE.md` (raiz) ficou desatualizado por este ADR** — a seção
  "Segurança" ainda descreve o comportamento de `require_api_key` como se
  fosse o guard ativo. Corrigido junto com este ADR.
- Sem RBAC nesta etapa: um único usuário, sem papéis/permissões
  diferenciadas. Se a plataforma ganhar mais de um usuário de verdade, isso
  é a próxima etapa — não coberta aqui.
- `require_api_key` fica como código morto de fato (nenhuma rota o usa mais),
  mas não foi removido nesta mudança — decisão de limpeza separada.
- Ferramentas externas (CI, cline, cursor, aider) continuam funcionando sem
  mudança nenhuma: elas nunca passaram pelo cookie de sessão, só pela API key,
  que `require_session` continua aceitando.
- Trello (`agent/tools/trello.py`) e identidade Git por projeto
  (`workspace/git.py::get_git_user_config`/`update_git_user_config`) foram
  ajustados no mesmo lote de commits para respeitar o projeto ativo em vez de
  uma configuração global única — consequência natural de existir agora um
  usuário "dono" da sessão, não uma decisão de segurança separada.

## Alternativas rejeitadas

- **bcrypt/argon2 em vez de `scrypt` da stdlib.** Mais forte contra GPU
  cracking em teoria, mas adiciona dependência com wheel nativo — fricção
  real em ambiente Windows sem MSVC Build Tools, que é o ambiente de
  desenvolvimento deste projeto. `scrypt` da stdlib com parâmetros
  conservadores (`N=2^14, r=8, p=1`) foi considerado suficiente para
  single-user local-first, não para multi-tenant em escala.
- **JWT sem estado em vez de sessão em tabela.** Revogar um JWT antes de
  expirar exige blocklist de qualquer forma — a tabela `AuthSession` já dá
  revogação trivial (`revoke_other_sessions`) sem reintroduzir esse problema
  por trás de outro nome.
- **Manter só a API key, sem conta de usuário.** Resolve o caso de uso atual
  (um operador, uma máquina), mas não abre caminho para múltiplos usuários
  nem para saber quem aprovou uma ação `WRITE`/`EXEC` — informação que a
  auditoria (`audit/`) já registra por sessão de agente, mas não por pessoa.
