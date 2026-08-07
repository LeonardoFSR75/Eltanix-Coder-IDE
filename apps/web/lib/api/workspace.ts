/**
 * Árvore de arquivos, CRUD de workspace e busca/substituição em projeto —
 * `/api/workspace/*`.
 */

import { del, get, post, put } from "@/lib/client";

export interface WorkspaceEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size_bytes: number;
}

export interface FileContent {
  path: string;
  content: string;
  language: string | null;
  lines: number;
}

export interface SearchMatch {
  path: string;
  line: number;
  column: number;
  text: string;
  preview: string;
}

export interface SearchResult {
  matches: SearchMatch[];
  files_with_matches: number;
  files_searched: number;
  truncated: boolean;
}

export interface ReplaceResult {
  files_changed: number;
  replacements: number;
}

export async function listTree(project: string, subpath: string): Promise<WorkspaceEntry[]> {
  const { entries } = await get<{ entries: WorkspaceEntry[] }>(
    `/api/workspace/tree?project=${encodeURIComponent(project)}&subpath=${encodeURIComponent(subpath)}`,
  );
  return entries;
}

export async function readFile(project: string, path: string): Promise<FileContent> {
  return get<FileContent>(
    `/api/workspace/file?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
  );
}

export async function writeFile(project: string, path: string, content: string): Promise<void> {
  await put("/api/workspace/file", { project, path, content });
}

export async function createEntry(project: string, path: string, isDir: boolean): Promise<void> {
  await post("/api/workspace/file", { project, path, is_dir: isDir });
}

export async function moveEntry(
  project: string,
  source: string,
  destination: string,
): Promise<void> {
  await post("/api/workspace/move", { project, source, destination });
}

export async function deleteEntry(
  project: string,
  path: string,
  recursive: boolean,
): Promise<void> {
  await del(
    `/api/workspace/file?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}&recursive=${recursive}`,
  );
}

export async function searchWorkspace(
  project: string,
  query: string,
  options: { regex: boolean; caseSensitive: boolean },
): Promise<SearchResult> {
  return post<SearchResult>("/api/workspace/search", {
    project,
    query,
    regex: options.regex,
    case_sensitive: options.caseSensitive,
  });
}

export async function replaceInWorkspace(
  project: string,
  query: string,
  replacement: string,
  options: { regex: boolean; caseSensitive: boolean },
): Promise<ReplaceResult> {
  return post<ReplaceResult>("/api/workspace/replace", {
    project,
    query,
    replacement,
    regex: options.regex,
    case_sensitive: options.caseSensitive,
  });
}
