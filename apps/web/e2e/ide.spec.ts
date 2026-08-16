import { test, expect } from "@playwright/test";
import { idePath } from "./helpers";

test("abre um projeto no IDE e o Monaco carrega", async ({ page }) => {
  await page.goto(idePath());

  // `.monaco-editor` é a classe que o próprio Monaco injeta ao montar — sinal
  // de que o editor de verdade inicializou, não só o chrome ao redor dele.
  await expect(page.locator(".monaco-editor").first()).toBeVisible({ timeout: 20_000 });

  // Barra de atividades (Explorer, Git, Navegador...) confirma que o resto do
  // shell do IDE também renderizou, não só o painel central.
  await expect(page.getByRole("button", { name: "Navegador (verificação visual)" })).toBeVisible();
});
