/**
 * Status, branches e operações de stage/commit — `/api/git/*`.
 */

import { get, post } from "@/lib/client";

export interface GitFile {
  path: string;
  status: string;
}

export interface GitStatus {
  branch: string;
  dirty: boolean;
  files: GitFile[];
}

export interface FileVersions {
  original: string;
  modified: string;
}

export async function getGitStatus(project: string): Promise<GitStatus> {
  return get<GitStatus>(`/api/git/status?project=${encodeURIComponent(project)}`);
}

export async function getGitBranches(project: string): Promise<string[]> {
  const { branches } = await get<{ branches: string[] }>(
    `/api/git/branches?project=${encodeURIComponent(project)}`,
  );
  return branches;
}

export async function checkoutBranch(
  project: string,
  branch: string,
  create = false,
): Promise<void> {
  await post("/api/git/checkout", { project, branch, create });
}

export async function stageFiles(project: string, paths: string[]): Promise<void> {
  await post("/api/git/stage", { project, paths });
}

export async function unstageFiles(project: string, paths: string[]): Promise<void> {
  await post("/api/git/unstage", { project, paths });
}

export async function commitChanges(project: string, message: string): Promise<void> {
  await post("/api/git/commit", { project, message });
}

export async function discardChanges(project: string, paths: string[]): Promise<void> {
  await post("/api/git/discard", { project, paths });
}

export async function getFileVersions(project: string, path: string): Promise<FileVersions> {
  return get<FileVersions>(
    `/api/git/file-versions?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
  );
}
