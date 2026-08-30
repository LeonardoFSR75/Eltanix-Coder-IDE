import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Espelha o "@/*" de tsconfig.json — sem isto, os mesmos imports que o app
// usa não resolveriam nos testes.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    // Sem uma origin http(s) explícita, o jsdom fica em `about:blank` (origin
    // opaca) e a spec de Storage desliga localStorage/sessionStorage nesse
    // caso — `lib/client.ts` usa `localStorage` de verdade, então precisa
    // disto pra não quebrar em todo teste que passa por ele.
    environmentOptions: {
      jsdom: { url: "http://localhost:3000" },
    },
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // e2e/ são specs Playwright (rodam via `npm run test:e2e` contra a stack
    // Docker inteira, ver e2e/README ou apps/web/CLAUDE.md) — sem isto, o
    // glob padrão de spec do Vitest as pega também e elas quebram, porque
    // usam o `test()`/`test.use()` do @playwright/test, não do Vitest.
    // `.claude/worktrees/**` são cópias temporárias do próprio repo criadas
    // por agentes (`EnterWorktree`) — sem excluir, o Vitest roda a suíte
    // inteira DUAS vezes (uma por cópia), o que também dobra o tempo de
    // execução e reporta falhas fantasmas vindas de código já obsoleto lá
    // dentro.
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**", "**/.claude/**"],
    // Padrão do Vitest 4 é 5s — curto demais para specs com `userEvent`
    // (várias interações de teclado/clique em sequência) rodando sob carga
    // paralela; a suíte ficava com falhas por timeout que só reproduziam
    // rodando o arquivo isolado.
    testTimeout: 15_000,
  },
});
