/** Nome (e slug) do projeto de fumaça compartilhado por toda a suíte E2E —
 * criado uma vez em `setup/project.setup.ts`, reaproveitado pelas specs. */
export const E2E_PROJECT_NAME = process.env.E2E_PROJECT_NAME ?? "e2e-smoke-test";

export function idePath(project: string = E2E_PROJECT_NAME): string {
  return `/ide?project=${encodeURIComponent(project)}`;
}
