import { test, expect } from "@playwright/test";

// Sobrepõe o storageState logado herdado do projeto `chromium` — este spec
// testa justamente os caminhos SEM sessão.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("login (ADR 0005 — nunca aberto por omissão)", () => {
  test("redireciona para /login quando não há cookie de sessão", async ({ page }) => {
    await page.goto("/projects");
    await expect(page).toHaveURL(/\/login/);
  });

  test("rejeita credenciais inválidas e mantém o usuário na tela de login", async ({ page }) => {
    await page.goto("/login");
    await page.locator("#username-input").fill("admin");
    await page.locator("#password-input").fill("senha-com-certeza-errada");
    await page.getByRole("button", { name: /entrar/i }).click();

    await expect(page.getByText("Usuário ou senha inválidos.")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });
});
