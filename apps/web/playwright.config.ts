import { defineConfig, devices } from "@playwright/test";

/**
 * E2E roda contra a stack já de pé via `docker compose up -d` (ver
 * ../../CLAUDE.md) — não sobe servidor nenhum sozinho, porque a stack real
 * depende de Postgres/Redis/MinIO/executor/browser, que o Playwright não tem
 * como orquestrar. `webServer` fica de fora de propósito.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:5400";

export default defineConfig({
  testDir: "./e2e",
  // Os testes reaproveitam um único usuário seed e um único projeto de
  // fumaça (ver e2e/setup/) contra a stack real, sem banco de teste
  // descartável — rodar em série evita duas specs colidirem na mesma sessão
  // de navegador ou no mesmo projeto.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  timeout: 30_000,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "auth-setup", testMatch: /e2e\/setup\/auth\.setup\.ts/ },
    {
      name: "project-setup",
      testMatch: /e2e\/setup\/project\.setup\.ts/,
      dependencies: ["auth-setup"],
      use: { storageState: "e2e/.auth/user.json" },
    },
    {
      name: "chromium",
      testMatch: /.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/user.json" },
      dependencies: ["project-setup"],
    },
  ],
});
