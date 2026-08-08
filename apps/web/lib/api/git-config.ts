import { get, post, put } from "@/lib/client";

export interface GitUserConfig {
  user_name: string;
  user_email: string;
  default_branch: string;
  autocrlf: string;
  gpg_sign: boolean;
  signing_key: string | null;
  local_user_name: string | null;
  local_user_email: string | null;
  ssh_keys: string[];
  has_ssh: boolean;
}

export interface GitConfigUpdateRequest {
  user_name?: string;
  user_email?: string;
  default_branch?: string;
  autocrlf?: string;
  gpg_sign?: boolean;
  signing_key?: string;
  scope?: "global" | "local";
  project?: string;
}

export interface GitHubUserProfile {
  login: string;
  name?: string | null;
  email?: string | null;
  avatar_url?: string | null;
  html_url?: string | null;
  bio?: string | null;
  public_repos?: number;
  total_private_repos?: number;
  created_at?: string;
}

export interface GitHubConfigResponse {
  status: "authenticated" | "not_authenticated" | "not_configured" | "error";
  token_configured: boolean;
  token_source: "settings" | "gh_cli" | "none";
  masked_token?: string;
  error?: string | null;
  user: GitHubUserProfile | null;
}

export interface GitHubTokenTestResponse {
  valid: boolean;
  error?: string | null;
  user?: GitHubUserProfile | null;
}

export async function getGitConfig(project?: string): Promise<GitUserConfig> {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return get<GitUserConfig>(`/api/git/config${query}`);
}

export async function updateGitConfig(payload: GitConfigUpdateRequest): Promise<GitUserConfig> {
  return put<GitUserConfig>("/api/git/config", payload);
}

export async function getGitHubConfig(): Promise<GitHubConfigResponse> {
  return get<GitHubConfigResponse>("/api/git/github/config");
}

export async function testGitHubToken(token: string): Promise<GitHubTokenTestResponse> {
  return post<GitHubTokenTestResponse>("/api/git/github/config/test", { token });
}

export async function updateGitHubConfig(github_token: string): Promise<GitHubConfigResponse> {
  return put<GitHubConfigResponse>("/api/git/github/config", { github_token });
}
