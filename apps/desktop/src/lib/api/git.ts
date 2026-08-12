/**
 * Painel Git do editor — `/api/git/*`. Opera no projeto que você está
 * editando (diferente das ferramentas Git do agente, que operam no worktree
 * da sessão). Porta simplificada do equivalente em `apps/web/lib/api/git.ts`.
 */

import { get, post } from "../client";

export type GitFileStatus = "added" | "modified" | "deleted" | "renamed" | "untracked" | "staged";

export interface GitFile {
  path: string;
  status: GitFileStatus;
}

export interface GitStatus {
  branch: string;
  head: string;
  dirty: boolean;
  files: GitFile[];
}

export interface GitDiffResult {
  diff: string;
  staged: boolean;
  path: string | null;
}

export interface GitBranches {
  current: string;
  branches: string[];
}

export function getGitStatus(project: string): Promise<GitStatus> {
  return get<GitStatus>(`/api/git/status?project=${encodeURIComponent(project)}`);
}

export function getGitDiff(project: string, path?: string, staged = false): Promise<GitDiffResult> {
  const params = new URLSearchParams({ project, staged: String(staged) });
  if (path) params.set("path", path);
  return get<GitDiffResult>(`/api/git/diff?${params.toString()}`);
}

export function stageFiles(project: string, paths: string[]): Promise<{ staged: string[] }> {
  return post<{ staged: string[] }>("/api/git/stage", { project, paths });
}

export function unstageFiles(project: string, paths: string[]): Promise<{ unstaged: string[] }> {
  return post<{ unstaged: string[] }>("/api/git/unstage", { project, paths });
}

export function commitChanges(
  project: string,
  message: string,
  paths?: string[],
): Promise<{ sha: string }> {
  return post<{ sha: string }>("/api/git/commit", { project, message, paths });
}

export function getBranches(project: string): Promise<GitBranches> {
  return get<GitBranches>(`/api/git/branches?project=${encodeURIComponent(project)}`);
}

export function checkoutBranch(
  project: string,
  branch: string,
  create = false,
): Promise<{ branch: string }> {
  return post<{ branch: string }>("/api/git/checkout", { project, branch, create });
}

export function discardChanges(project: string, paths: string[]): Promise<{ discarded: string[] }> {
  return post<{ discarded: string[] }>("/api/git/discard", { project, paths });
}
