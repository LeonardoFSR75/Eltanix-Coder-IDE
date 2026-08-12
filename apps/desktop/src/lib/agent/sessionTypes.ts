/**
 * Tipos compartilhados entre `sessionRuntime.ts` (motor sem framework, um por
 * sessão) e os componentes Svelte que renderizam seu estado — porta de
 * `apps/web/components/ide/agent/sessionTypes.ts`.
 */

export interface PendingAction {
  tool_call_id: string;
  tool: string;
  risk: string;
  arguments: Record<string, unknown>;
  summary: string;
}

export interface Session {
  session_id: string;
  branch: string;
  worktree_path: string;
  sandbox_available: boolean;
  sandbox_error: string | null;
  github_available: boolean;
  warnings: string[];
  profile?: string | null;
  model?: string | null;
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface LogLine {
  kind: "info" | "assistant" | "tool" | "error" | "cost" | "user";
  text: string;
  tool?: string;
  toolCallId?: string;
  toolOk?: boolean;
  toolData?: Record<string, unknown>;
  toolContent?: string;
}

/** Status derivado para o card do Agent Manager — nenhum campo novo no backend. */
export type SessionStatus = "running" | "awaiting-approval" | "done" | "error" | "closed";

export interface SessionSummary {
  id: string;
  task: string;
  mode: string;
  branch: string;
  status: SessionStatus;
  closed: boolean;
}
