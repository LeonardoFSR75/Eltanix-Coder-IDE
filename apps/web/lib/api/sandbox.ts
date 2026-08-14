import { get } from "@/lib/client";

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
