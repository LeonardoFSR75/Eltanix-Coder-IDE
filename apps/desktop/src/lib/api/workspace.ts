/**
 * Operações de workspace, árvore de diretórios e CRUD de arquivos — `/api/workspace/*`.
 */

import { del, get, HttpError, post, put } from "../client";

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

export async function listTree(project: string, subpath = ""): Promise<WorkspaceEntry[]> {
  const { entries } = await get<{ entries: WorkspaceEntry[] }>(
    `/api/workspace/tree?project=${encodeURIComponent(project)}&subpath=${encodeURIComponent(subpath)}`
  );
  return entries;
}

export async function readFile(project: string, path: string): Promise<FileContent> {
  return get<FileContent>(
    `/api/workspace/file?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`
  );
}

export async function writeFile(project: string, path: string, content: string): Promise<void> {
  await put("/api/workspace/file", { project, path, content });
}

export async function createEntry(project: string, path: string, isDir: boolean): Promise<void> {
  await post("/api/workspace/file", { project, path, is_dir: isDir });
}

export async function deleteEntry(project: string, path: string, recursive = true): Promise<void> {
  await del(
    `/api/workspace/file?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}&recursive=${recursive}`
  );
}

export interface FlatFile {
  path: string;
  name: string;
}

/** Lista plana do projeto inteiro, cacheada no backend — para quick open. */
export async function listAllFiles(project: string, refresh = false): Promise<FlatFile[]> {
  const { files } = await get<{ files: FlatFile[] }>(
    `/api/workspace/files?project=${encodeURIComponent(project)}&refresh=${refresh}`,
  );
  return files;
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
  files_searched: number;
  files_with_matches: number;
  truncated: boolean;
}

export interface SearchOptions {
  regex?: boolean;
  caseSensitive?: boolean;
  wholeWord?: boolean;
  pathGlob?: string;
  maxMatches?: number;
}

export async function searchInFiles(
  project: string,
  query: string,
  opts: SearchOptions = {},
): Promise<SearchResult> {
  return post<SearchResult>("/api/workspace/search", {
    project,
    query,
    regex: opts.regex ?? false,
    case_sensitive: opts.caseSensitive ?? false,
    whole_word: opts.wholeWord ?? false,
    path_glob: opts.pathGlob || undefined,
    max_matches: opts.maxMatches ?? 500,
  });
}

export interface ReplaceResult {
  files_changed: number;
  replacements: number;
  changed_paths: string[];
}

export async function replaceInFiles(
  project: string,
  query: string,
  replacement: string,
  opts: SearchOptions & { onlyPaths?: string[] } = {},
): Promise<ReplaceResult> {
  return post<ReplaceResult>("/api/workspace/replace", {
    project,
    query,
    replacement,
    regex: opts.regex ?? false,
    case_sensitive: opts.caseSensitive ?? false,
    whole_word: opts.wholeWord ?? false,
    path_glob: opts.pathGlob || undefined,
    only_paths: opts.onlyPaths ?? undefined,
  });
}
