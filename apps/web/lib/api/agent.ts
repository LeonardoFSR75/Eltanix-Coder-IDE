/**
 * Sessões, catálogo de ferramentas e reversão de arquivo do agente —
 * `/api/agent/*`.
 */

import { get, post } from "@/lib/client";

export interface AgentSessionRecord {
  session_id: string;
  project: string;
  task: string;
  mode: string;
  profile: string | null;
  branch: string | null;
  status: "open" | "closed";
  created_at: string;
  updated_at: string;
  live: boolean;
}

export interface AgentToolInfo {
  name: string;
  description: string;
  risk: string;
  requires_approval: boolean;
}

export async function listAgentSessions(
  project: string,
  limit = 50,
): Promise<AgentSessionRecord[]> {
  const { sessions } = await get<{ sessions: AgentSessionRecord[] }>(
    `/api/agent/sessions?project=${encodeURIComponent(project)}&limit=${limit}`,
  );
  return sessions;
}

export async function listAgentTools(): Promise<AgentToolInfo[]> {
  const { tools } = await get<{ tools: AgentToolInfo[] }>("/api/agent/tools");
  return tools;
}

export async function revertFile(
  sessionId: string,
  path: string,
  before: string,
  existed: boolean,
): Promise<void> {
  await post(`/api/agent/sessions/${sessionId}/files/revert`, { path, before, existed });
}
