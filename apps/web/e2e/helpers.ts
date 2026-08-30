import { expect, type Page } from "@playwright/test";

/** Nome (e slug) do projeto de fumaça compartilhado por toda a suíte E2E —
 * criado uma vez em `setup/project.setup.ts`, reaproveitado pelas specs. */
export const E2E_PROJECT_NAME = process.env.E2E_PROJECT_NAME ?? "e2e-smoke-test";

export function idePath(project: string = E2E_PROJECT_NAME): string {
  return `/ide?project=${encodeURIComponent(project)}`;
}

/**
 * Abre o IDE no projeto de fumaça e espera o Monaco montar DE VERDADE.
 *
 * O IDE sobe sem nenhum arquivo aberto — `Editor.tsx` renderiza só o estado
 * vazio ("Selecione um arquivo…") e nunca instancia `<MonacoEditor>`. É
 * abrir um arquivo da árvore do Explorer que carrega o chunk do editor e
 * injeta o `.monaco-editor` no DOM. `project.setup.ts` cria o projeto via
 * "Novo Projeto", que já vem com `.gitignore` e `requirements.txt` no root.
 */
export async function openIdeWithFile(page: Page, file = ".gitignore"): Promise<void> {
  await page.goto(idePath());

  const treeRow = page.getByRole("button", { name: file }).first();
  await expect(treeRow).toBeVisible({ timeout: 20_000 });
  await treeRow.click();

  await expect(page.locator(".monaco-editor").first()).toBeVisible({ timeout: 20_000 });
}
