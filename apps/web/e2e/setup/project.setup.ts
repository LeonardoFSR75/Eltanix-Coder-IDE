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

  // O card de cada projeto mostra o nome num <h3> e o slug num <span>, e o slug
  // do projeto de fumaça é igual ao nome — `getByText(nome, { exact })` casaria
  // os dois (strict mode violation). Mirar no heading do card resolve isso.
  const cardHeading = page.getByRole("heading", { name: E2E_PROJECT_NAME, exact: true });
  const emptyState = page.getByRole("heading", { name: "Nenhum projeto encontrado" });

  // A lista carrega por fetch depois que o heading da página aparece; esperar
  // ela assentar (card presente OU estado vazio) antes de decidir criar evita
  // a corrida que fazia o teste criar um projeto duplicado a cada tentativa.
  await expect
    .poll(async () => (await cardHeading.count()) > 0 || (await emptyState.count()) > 0, {
      timeout: 15_000,
    })
    .toBe(true);

  if (await cardHeading.count()) {
    return;
  }

  await page.getByRole("button", { name: "Novo Projeto" }).click();
  await page.getByPlaceholder("ex: meu-sistema-v2").fill(E2E_PROJECT_NAME);
  await page.getByRole("button", { name: "Criar Projeto" }).click();

  await expect(cardHeading).toBeVisible({ timeout: 15_000 });
});
