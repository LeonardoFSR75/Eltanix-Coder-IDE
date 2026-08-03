# apps/web

Next.js (App Router) + TypeScript + Monaco + xterm. Ver [../CLAUDE.md](../CLAUDE.md) para
invariantes de arquitetura.

## Comandos

```bash
npm run typecheck   # tsc --noEmit — rodar sempre após mudar algo aqui
npm run build       # next build — pega erros que o typecheck sozinho não pega
npm run dev          # servidor local (dentro do container isso já roda via docker compose)
```

**`node_modules` não é bind-mounted** (só `app/`, `components/`, `lib/` são — ver
`docker-compose.yml`): mudar `package.json` exige `docker compose build web` e
`docker compose up -d web` para o container pegar a mudança. Editar código dentro de
`app/components/lib` reflete sozinho (hot-reload via `WATCHPACK_POLLING`).

## Regra que não se quebra: `lib/client.ts` é o único cliente HTTP

Nenhum componente chama `fetch()` direto contra o backend. Tudo passa por
`get`/`post`/`put`/`del`/`streamEvents` de `lib/client.ts`, que fala com
`/api/gateway/[...path]` — a única rota que anexa `Authorization` no servidor (a chave
nunca chega ao bundle do browser, ver `route.ts`). Um `lib/api/<domínio>.ts` novo (ex.
`lib/api/telemetry.ts`) é uma casca fina em cima dessas funções, tipando request/response
— não recria a lógica de fetch.

## Estrutura

| Pasta | O quê |
|---|---|
| `app/` | Rotas do App Router — uma pasta por página (`/mcp`, `/settings`, `/rag`...), mais `app/api/gateway/[...path]/route.ts` (o proxy) |
| `components/ide/` | Monaco, terminal (xterm), agent dock, painéis do IDE |
| `components/providers/` | Contextos globais — `AuthContext.tsx` (chave de API), `Toast.tsx` |
| `lib/client.ts` | Único cliente HTTP — ver regra acima |
| `lib/api/*.ts` | Um arquivo por domínio de backend (`documents.ts`, `notes.ts`, `mcp.ts`, `telemetry.ts`...), tipos + funções finas sobre `lib/client.ts` |

## Padrões a seguir em página/feature nova

- Página nova que fala com o backend: criar `lib/api/<domínio>.ts` primeiro (tipos +
  funções), depois a página consome via `useEffect`/`useState` chamando essas funções —
  nunca inline fetch na página.
- Handoff para o agente (botão "Testar no Agente" em `/mcp`, `/rag`, `/skills`): navegar
  para `/ide?agentPrompt=<texto>` — o `AgentDock.tsx` já lê esse query param uma vez via
  `window.location.search` e preenche o textarea. Não duplicar esse mecanismo.
- Tabela de dados simples: `<div className="table-wrap"><table>...` (ver `requests/page.tsx`
  ou o painel de telemetria em `settings/page.tsx`) — não inventar classe CSS nova para isso.
