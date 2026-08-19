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
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
  },
});
