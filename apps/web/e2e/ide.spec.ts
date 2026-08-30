import { test, expect } from "@playwright/test";
import { openIdeWithFile } from "./helpers";

test("abre um projeto no IDE e o Monaco carrega", async ({ page }) => {
  // O IDE abre sem arquivo aberto; `openIdeWithFile` clica um arquivo da
  // árvore e só volta quando `.monaco-editor` — a classe que o próprio Monaco
  // injeta ao montar — está visível, provando que o editor de verdade
  // inicializou (assets locais de `/vs`, sem CDN), não só o chrome ao redor.
  await openIdeWithFile(page);

  // Barra de atividades (Explorer, Git, Navegador...) confirma que o resto do
  // shell do IDE também renderizou, não só o painel central.
  await expect(page.getByRole("button", { name: "Navegador (verificação visual)" })).toBeVisible();
});
