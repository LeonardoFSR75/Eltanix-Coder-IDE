# apps/desktop

Svelte 5 + Vite + TypeScript + Monaco + Xterm.js + Tauri.
Ver [../CLAUDE.md](../CLAUDE.md) para invariantes de arquitetura.

## Comandos

```bash
npm run typecheck   # svelte-check --tsconfig ./tsconfig.json
npm run test         # vitest run — testes de unidade
npm run build        # vite build
npm run dev          # servidor dev local (Svelte 5 em http://localhost:5409)
npm run tauri dev    # compila e roda a janela nativa do app desktop
```

## Regra de Conexão com API

Todas as chamadas para o backend passam por `src/lib/client.ts` (`get`, `post`, `put`, `del`, `streamEvents`), que utiliza `VITE_API_ORIGIN` (padrão `http://localhost:5401`) e envia a chave de autorização configurada localmente.
