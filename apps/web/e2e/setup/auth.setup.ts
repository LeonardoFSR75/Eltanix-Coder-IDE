import { test as setup, expect } from "@playwright/test";

/**
 * Login real via UI, salvando o cookie httpOnly de sessão em disco
 * (`storageState`) para os demais projetos reaproveitarem — evita logar de
 * novo em cada spec, e ainda assim exercita o fluxo real de autenticação
 * (ADR 0005) uma vez por execução da suíte.
 */
const authFile = "e2e/.auth/user.json";

setup("login", async ({ page }) => {
  const username = process.env.E2E_USERNAME ?? "admin";
  const password = process.env.E2E_PASSWORD;
  if (!password) {
    throw new Error(
      "E2E_PASSWORD não definido. Defina a mesma senha de NOVAAI_STUDIO_ADMIN_PASSWORD do " +
        ".env (ver apps/web/CLAUDE.md, seção 'Testes E2E') antes de rodar `npm run test:e2e`.",
    );
  }

  await page.goto("/login");
  await page.locator("#username-input").fill(username);
  await page.locator("#password-input").fill(password);
  await page.getByRole("button", { name: /entrar/i }).click();

  await expect(page).toHaveURL(/\/projects/, { timeout: 15_000 });

  await page.context().storageState({ path: authFile });
});
