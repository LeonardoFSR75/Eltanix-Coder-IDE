/**
 * Cliente da API de Projetos (`/api/projects/*`) integrado ao Hub Principal.
 */

import { del, get, post } from "../client";

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
  branch: string | null;
  total_cost_usd: number;
  total_tokens: number;
  active_sessions_count: number;
}

export interface ProjectCreateIn {
  name: string;
  description?: string;
  git_url?: string;
  init_git?: boolean;
}

export async function listProjects(): Promise<ProjectRecord[]> {
  try {
    const data = await get<{ projects: ProjectRecord[] }>("/api/projects");
    if (data && Array.isArray(data.projects)) {
      return data.projects;
    }
    return [];
  } catch (err) {
    console.warn("Falha ao carregar lista de projetos da API:", err);
    return [
      {
        id: "default",
        slug: "novaai-studio-code",
        name: "novaai-studio-code",
        description: "Projeto Principal",
        local_path: null,
        git_url: null,
        default_branch: "main",
        budget_limit_usd: null,
        settings: {},
      },
    ];
  }
}

export async function createProject(payload: ProjectCreateIn): Promise<ProjectRecord> {
  return post<ProjectRecord>("/api/projects", payload);
}

export async function getProjectSummary(slug: string): Promise<ProjectSummary | null> {
  try {
    return await get<ProjectSummary>(`/api/projects/${encodeURIComponent(slug)}/summary`);
  } catch {
    return null;
  }
}

export async function deleteProject(slug: string): Promise<void> {
  await del(`/api/projects/${encodeURIComponent(slug)}`);
}
