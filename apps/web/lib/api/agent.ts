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
  // "abandoned": aba fechada sem `close_session` explícito, reclamada pela
  // varredura periódica (`AGENT_SESSION_ABANDON_AFTER_HOURS`) — nunca setado
  // pelo usuário, só pela varredura.
  status: "open" | "closed" | "abandoned";
  // Preenchido só para sessões criadas via `spawn_agent` (orquestração
  // multiagente, ver ADR 0004) — `null` para qualquer sessão raiz.
  parent_session_id: string | null;
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

export type AgentLiveStatus =
  | "running"
  | "waiting_approval"
  | "waiting_for_message"
  | "completed"
  | "failed"
  | "stopped";

export interface AgentGraphNode {
  session_id: string;
  display_name: string;
  status: AgentLiveStatus;
  parent_id: string | null;
  depth: number;
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

export interface SlashCommandInfo {
  command: string;
  skill_name: string | null;
  suggested_mode: string | null;
  description: string;
}

/** Catálogo de slash commands reais do agente (`/spec`, `/test`, `/fix`...) —
 * cada um ativa deterministicamente uma skill do backend (`agent/slash_commands.py`).
 * Fonte única do servidor, consumida pelo autocomplete de `AgentChatInput.tsx`. */
export async function listSlashCommands(): Promise<SlashCommandInfo[]> {
  const { commands } = await get<{ commands: SlashCommandInfo[] }>("/api/agent/slash-commands");
  return commands;
}

/** Árvore de agentes a partir de `sessionId` (ele + todos os descendentes),
 * com status ao vivo do `AgentCoordinator` — inclusive `waiting_approval`
 * para um filho headless, que a lista de sessões sozinha não revela. */
export async function getAgentGraph(sessionId: string): Promise<AgentGraphNode[]> {
  const { agents } = await get<{ agents: AgentGraphNode[] }>(
    `/api/agent/sessions/${encodeURIComponent(sessionId)}/graph`,
  );
  return agents;
}

export async function revertFile(
  sessionId: string,
  path: string,
  before: string,
  existed: boolean,
): Promise<void> {
  await post(`/api/agent/sessions/${sessionId}/files/revert`, { path, before, existed });
}

export async function acceptFile(sessionId: string, path: string): Promise<void> {
  await post(`/api/agent/sessions/${sessionId}/files/accept`, { path });
}

export interface SessionDiffFile {
  path: string;
  status: string;
}

export interface SessionDiff {
  branch: string;
  dirty: boolean;
  files: SessionDiffFile[];
  diff: string;
}

export async function getSessionDiff(sessionId: string): Promise<SessionDiff> {
  return get<SessionDiff>(`/api/agent/sessions/${encodeURIComponent(sessionId)}/diff`);
}

export interface AgentCheckpoint {
  iteration: number;
  created_at: string;
  summary: string;
  finished: boolean;
}

/** Pontos de restauração (Fase 8) — um por chamada ao modelo já concluída
 * nesta sessão. `[]` se o checkpointer estiver indisponível. */
export async function listCheckpoints(sessionId: string): Promise<AgentCheckpoint[]> {
  const { checkpoints } = await get<{ checkpoints: AgentCheckpoint[] }>(
    `/api/agent/sessions/${encodeURIComponent(sessionId)}/checkpoints`,
  );
  return checkpoints;
}

export interface RewindResult {
  iteration: number;
  files_restored: string[];
}

/** Restaura a sessão para o fim de `iteration`: trunca o histórico do grafo
 * e reverte no worktree todo arquivo escrito depois dela. Ação destrutiva —
 * sempre confirmar com o usuário antes de chamar. */
export async function rewindSession(sessionId: string, iteration: number): Promise<RewindResult> {
  return post<RewindResult>(`/api/agent/sessions/${encodeURIComponent(sessionId)}/rewind`, {
    iteration,
  });
}

