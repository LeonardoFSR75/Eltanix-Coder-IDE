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
