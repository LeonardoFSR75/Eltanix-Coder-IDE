/**
 * Cliente da API de Projetos (`/api/projects/*`).
 */

import { del, get, patch, post } from "@/lib/client";

export interface ProjectRecord {
  id: string;
  slug: string;
  name: string;
  description: string;
  local_path: string | null;
  git_url: string | null;
  default_branch: string;
  budget_limit_usd: number | null;
  settings: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectSummary {
  slug: string;
  name: string;
  description: string;
  local_path: string | null;
  git_url: string | null;
  is_git: boolean;
  branch: string | null;
  budget_limit_usd: number | null;
  total_cost_usd: number;
  total_tokens: number;
  notes_count: number;
  documents_count: number;
  graph_nodes_count: number;
  graph_edges_count: number;
  audit_events_count: number;
  active_sessions_count: number;
  recent_commits: { sha: string; author: string; date: string; message: string }[];
  settings: Record<string, any>;
}

export interface ProjectCreateIn {
  name: string;
  description?: string;
  language?: string;
  git_url?: string;
  init_git?: boolean;
  create_github_repo?: boolean;
  budget_limit_usd?: number;
  settings?: Record<string, any>;
}

export interface ProjectUpdateIn {
  name?: string;
  description?: string;
  git_url?: string;
  budget_limit_usd?: number;
  settings?: Record<string, any>;
}

export interface ProjectSignature {
  name: string;
  path: string;
  primary_language: string;
  frameworks: string[];
  build_system: string;
  has_docker: boolean;
  has_git: boolean;
  has_ci_cd: boolean;
  summary: string;
}

export interface FsRoot {
  name: string;
  path: string;
  icon: string;
  type: string;
}

export interface FsDirectory {
  name: string;
  path: string;
  has_git: boolean;
  is_project: boolean;
}

export interface FsBrowseResult {
  current_path: string | null;
  parent_path: string | null;
  breadcrumbs: { name: string; path: string }[];
  roots: FsRoot[];
  directories: FsDirectory[];
  // Quando `true`, `directories` foi cortada em 120 entradas — há mais
  // subpastas do que o listado (`total_directories` diz quantas ao todo).
  truncated?: boolean;
  total_directories?: number;
}

export async function listProjects(): Promise<ProjectRecord[]> {
  const data = await get<{ projects: ProjectRecord[] }>("/api/projects");
  return data.projects;
}

export async function createProject(payload: ProjectCreateIn): Promise<ProjectRecord> {
  return post<ProjectRecord>("/api/projects", payload);
}

export async function openAbsolutePath(path: string): Promise<ProjectSignature & { slug: string }> {
  return post<ProjectSignature & { slug: string }>("/api/projects/open-path", { path });
}

export async function inspectPath(path: string): Promise<ProjectSignature> {
  return post<ProjectSignature>("/api/projects/inspect-path", { path });
}

export async function browseFilesystem(path?: string): Promise<FsBrowseResult> {
  return post<FsBrowseResult>("/api/projects/filesystem/browse", { path: path || null });
}

export async function getProjectSummary(slug: string): Promise<ProjectSummary> {
  return get<ProjectSummary>(`/api/projects/${encodeURIComponent(slug)}/summary`);
}

export async function updateProject(slug: string, payload: ProjectUpdateIn): Promise<ProjectRecord> {
  return patch<ProjectRecord>(`/api/projects/${encodeURIComponent(slug)}`, payload);
}

export async function deleteProject(slug: string, deleteFiles: boolean = false): Promise<void> {
  await del(`/api/projects/${encodeURIComponent(slug)}?delete_files=${deleteFiles}`);
}
