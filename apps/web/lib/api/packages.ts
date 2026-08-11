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
  const res = await fetch(`/api/gateway/api/projects/${encodeURIComponent(slug)}/packages/uninstall`, {
    method: "DELETE",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      package: packageName,
      save_requirements: saveRequirements,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.error || "Falha ao desinstalar pacote");
  }
  return res.json();
}

export async function syncProjectRequirements(slug: string): Promise<SyncRequirementsResult> {
  return post<SyncRequirementsResult>(`/api/projects/${encodeURIComponent(slug)}/packages/sync`);
}
