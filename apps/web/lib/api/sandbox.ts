import { get, post } from "@/lib/client";

export interface SandboxMetrics {
  memory_bytes?: number;
  memory_mb?: number;
  memory_limit_mb?: number;
  pids_count?: number;
}

export interface SandboxStats {
  session_id: string;
  name?: string;
  status: string;
  ports: number[];
  metrics?: SandboxMetrics;
}

export interface SandboxServerLogs {
  session_id: string;
  logs: string;
}

export interface WebAppToggleResponse {
  session_id: string;
  is_web_app: boolean;
  web_prewarmed: boolean;
}

export async function getSandboxStats(sessionId: string): Promise<SandboxStats> {
  return get<SandboxStats>(`/api/agent/sessions/${encodeURIComponent(sessionId)}/sandbox/stats`);
}

export async function getSandboxServerLogs(
  sessionId: string,
  tail: number = 100,
): Promise<SandboxServerLogs> {
  return get<SandboxServerLogs>(
    `/api/agent/sessions/${encodeURIComponent(sessionId)}/sandbox/logs?tail=${tail}`,
  );
}

export async function toggleWebApp(
  sessionId: string,
  enabled: boolean,
): Promise<WebAppToggleResponse> {
  return post<WebAppToggleResponse>(
    `/api/agent/sessions/${encodeURIComponent(sessionId)}/web-app`,
    { enabled },
  );
}

