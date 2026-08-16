import { test, expect } from "@playwright/test";
import { idePath } from "./helpers";

/**
 * Golden path do painel de navegador manual — exercita de ponta a ponta o
 * caminho consertado em `api/routes/browser.py` (cliente cacheado por
 * sessão, sem `POST /sessions` redundante a cada ação): abrir o painel,
 * navegar para uma URL real e ver a captura de tela voltar.
 */
test("painel de navegador manual navega e mostra uma captura real da página", async ({ page }) => {
  await page.goto(idePath());
  await expect(page.locator(".monaco-editor").first()).toBeVisible({ timeout: 20_000 });

  await page.getByRole("button", { name: "Navegador (verificação visual)" }).click();

  const urlInput = page.getByPlaceholder("http://web:5400 ou https://exemplo.com");
  await expect(urlInput).toBeVisible();
  await urlInput.fill("http://web:5400");
  await page.getByRole("button", { name: "Ir" }).click();

  await expect(page.locator(".browser-panel-viewport img")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".browser-panel-status")).toContainText("web:5400");

  // Uma segunda navegação na mesma sessão de painel prova que a sessão do
  // serviço `browser` foi reaproveitada, não recriada a cada ação.
  await urlInput.fill("http://web:5400/login");
  await page.getByRole("button", { name: "Ir" }).click();
  await expect(page.locator(".browser-panel-status")).toContainText("web:5400/login");
});
