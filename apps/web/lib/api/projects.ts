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
  graph_nodes_count: number;
  graph_edges_count: number;
  audit_events_count: number;
  active_sessions_count: number;
  settings: Record<string, any>;
}

export interface ProjectCreateIn {
  name: string;
  description?: string;
  git_url?: string;
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

export async function listProjects(): Promise<ProjectRecord[]> {
  const data = await get<{ projects: ProjectRecord[] }>("/api/projects");
  return data.projects;
}

export async function createProject(payload: ProjectCreateIn): Promise<ProjectRecord> {
  return post<ProjectRecord>("/api/projects", payload);
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
