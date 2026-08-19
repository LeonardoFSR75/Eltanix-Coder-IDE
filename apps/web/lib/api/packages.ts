/**
 * Cliente da API de Pacotes do Projeto (`/api/projects/{slug}/packages/*`).
 */

import { del, get, post } from "@/lib/client";

export interface PackageItem {
  name: string;
  version: string;
}

export interface ProjectPackagesResponse {
  project: string;
  ecosystem?: string;
  manifest_file?: string;
  venv_exists: boolean;
  venv_path: string;
  installed_count: number;
  packages: PackageItem[];
  requirements_exists: boolean;
  requirements_content: string;
  requirements_map: Record<string, string>;
}

export interface InstallPackageResult {
  ok: boolean;
  package: string;
  version: string | null;
  requirements_updated: boolean;
  requirements_content: string;
  stdout: string;
}

export interface UninstallPackageResult {
  ok: boolean;
  package: string;
  requirements_updated: boolean;
  requirements_content: string;
  stdout: string;
}

export interface SyncRequirementsResult {
  ok: boolean;
  message: string;
  stdout: string;
}

export async function getProjectPackages(slug: string): Promise<ProjectPackagesResponse> {
  return get<ProjectPackagesResponse>(`/api/projects/${encodeURIComponent(slug)}/packages`);
}

export async function installProjectPackage(
  slug: string,
  packageName: string,
  saveRequirements: boolean = true
): Promise<InstallPackageResult> {
  return post<InstallPackageResult>(`/api/projects/${encodeURIComponent(slug)}/packages/install`, {
    package: packageName,
    save_requirements: saveRequirements,
  });
}

export async function uninstallProjectPackage(
  slug: string,
  packageName: string,
  saveRequirements: boolean = true
): Promise<UninstallPackageResult> {
  return del<UninstallPackageResult>(`/api/projects/${encodeURIComponent(slug)}/packages/uninstall`, {
    package: packageName,
    save_requirements: saveRequirements,
  });
}

export async function syncProjectRequirements(slug: string): Promise<SyncRequirementsResult> {
  return post<SyncRequirementsResult>(`/api/projects/${encodeURIComponent(slug)}/packages/sync`);
}

export type PackagesSyncStatus = "ok" | "warning" | "idle";

const SYNC_IGNORED_PACKAGES = new Set(["pip", "setuptools", "wheel", "distribute"]);

function normalizePackageNameForSync(name: string): string {
  return name.trim().toLowerCase().replace(/[_\s]+/g, "-");
}

// Compartilhado entre `PackagesPanel` e o indicador da `StatusBar` — os dois
// precisam da mesma resposta para "o .venv bate com o manifesto?" a partir
// da mesma resposta de `getProjectPackages`, então vive aqui em vez de em
// cada componente (ao contrário da duplicação deliberada entre as fontes de
// RAG, aqui é só aritmética pura sobre a mesma forma de dado).
export function resolvePackagesSyncStatus(
  installed: PackageItem[],
  requirementsMap: Record<string, string>
): PackagesSyncStatus {
  const installedNames = new Set(
    installed
      .map((pkg) => normalizePackageNameForSync(pkg.name))
      .filter((name) => !SYNC_IGNORED_PACKAGES.has(name))
  );
  const reqNames = new Set(
    Object.keys(requirementsMap)
      .map((name) => normalizePackageNameForSync(name))
      .filter((name) => !SYNC_IGNORED_PACKAGES.has(name))
  );

  if (installedNames.size === 0) return "idle";
  const hasMismatch = [...installedNames].some((name) => !reqNames.has(name));
  return hasMismatch ? "warning" : "ok";
}
