import { test as setup, expect } from "@playwright/test";
import { E2E_PROJECT_NAME } from "../helpers";

/**
 * Garante que o projeto de fumaça existe, sem recriá-lo a cada execução —
 * `createProject` não é idempotente do lado do backend, então checar a
 * Central de Projetos primeiro evita acumular um projeto novo por rodada.
 */
setup("garante que o projeto de fumaça do E2E existe", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Central do Projeto" })).toBeVisible();

  if (await page.getByText(E2E_PROJECT_NAME, { exact: true }).count()) {
    return;
  }

  await page.getByRole("button", { name: "Novo Projeto" }).click();
  await page.getByPlaceholder("ex: meu-sistema-v2").fill(E2E_PROJECT_NAME);
  await page.getByRole("button", { name: "Criar Projeto" }).click();

  await expect(page.getByText(E2E_PROJECT_NAME, { exact: true })).toBeVisible({ timeout: 15_000 });
});
