"use client";

/**
 * Ciclo de vida de uma sessão do agente: criar, transmitir eventos por SSE,
 * decidir aprovações. Extraído do antigo `AgentPanel.tsx` sem mudança de
 * comportamento — só isolamento, para o painel novo poder compor cabeçalho,
 * histórico e input em componentes separados sobre o mesmo estado.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { post, streamEvents } from "@/lib/client";
import type { Mode } from "./modes";

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
}

export interface LogLine {
  kind: "info" | "assistant" | "tool" | "error" | "cost";
  text: string;
}

export function useAgentSession({
  project,
  onFileTouched,
  onSession,
}: {
  project: string | null;
  onFileTouched?: (path: string) => void;
  onSession?: (sessionId: string | null) => void;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Uma execução em andamento não pode continuar atualizando estado depois
  // que o painel some — o backend segue rodando, mas o React descartaria a
  // atualização de um componente desmontado em silêncio, e o usuário nunca
  // saberia se a tarefa terminou.
  useEffect(() => () => abortRef.current?.abort(), []);

  const append = useCallback((line: LogLine) => {
    setLog((prev) => [...prev, line]);
  }, []);

  const consume = useCallback(
    (event: unknown) => {
      const { node, update } = (event ?? {}) as { node?: string; update?: Record<string, unknown> };
      if (!node || !update) return;

      if (node === "error") {
        append({ kind: "error", text: String(update.message ?? "erro desconhecido") });
        return;
      }

      if (node === "interrupt" || update.type === "approval_required") {
        const actions = (update.actions ?? []) as PendingAction[];
        setPending(actions);
        setRunning(false);
        return;
      }

      if (node === "think") {
        const messages = (update.messages ?? []) as Array<Record<string, unknown>>;
        for (const message of messages) {
          const content = message.content;
          if (typeof content === "string" && content.trim()) {
            append({ kind: "assistant", text: content });
          }
        }
        if (typeof update.total_cost_usd === "number") {
          append({
            kind: "cost",
            text: `${update.total_tokens ?? 0} tokens · $${Number(update.total_cost_usd).toFixed(4)}`,
          });
        }
        const acoes = (update.pending ?? []) as PendingAction[];
        if (acoes.length > 0) setPending(acoes);
      }

      if (node === "act") {
        const messages = (update.messages ?? []) as Array<Record<string, unknown>>;
        for (const message of messages) {
          append({
            kind: "tool",
            text: `${message.name}: ${String(message.content ?? "").slice(0, 1200)}`,
          });
        }
        for (const path of (update.files_changed ?? []) as string[]) {
          onFileTouched?.(path);
        }
      }
    },
    [append, onFileTouched],
  );

  const run = useCallback(
    async (currentSession: Session, approvals?: Record<string, { approved: boolean; reason: string }>) => {
      setRunning(true);
      setPending([]);
      abortRef.current = new AbortController();

      try {
        await streamEvents(
          `/api/agent/sessions/${currentSession.session_id}/run`,
          approvals ? { approvals } : {},
          consume,
          abortRef.current.signal,
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          append({ kind: "error", text: err instanceof Error ? err.message : String(err) });
        }
      } finally {
        setRunning(false);
      }
    },
    [consume, append],
  );

  const start = useCallback(
    async (task: string, mode: Mode, profile?: string | null) => {
      if (!task.trim() || !project) return;
      setLog([]);
      setPending([]);
      try {
        const created = await post<Session>("/api/agent/sessions", {
          task,
          mode,
          project,
          profile: profile || undefined,
        });
        setSession(created);
        onSession?.(created.session_id);
        append({ kind: "info", text: `sessão ${created.session_id} · branch ${created.branch || "(nenhum)"}` });
        for (const aviso of created.warnings ?? []) {
          append({ kind: "error", text: aviso });
        }
        await run(created);
      } catch (err) {
        append({ kind: "error", text: err instanceof Error ? err.message : String(err) });
      }
    },
    [project, append, run, onSession],
  );

  const decide = useCallback(
    async (approved: boolean) => {
      if (!session) return;
      const approvals = Object.fromEntries(
        pending.map((action) => [
          action.tool_call_id,
          { approved, reason: approved ? "" : "recusado pelo usuário" },
        ]),
      );
      append({
        kind: "info",
        text: approved ? "ações aprovadas" : "ações recusadas",
      });
      await run(session, approvals);
    },
    [session, pending, append, run],
  );

  const resetForNewSession = useCallback(() => {
    abortRef.current?.abort();
    setSession(null);
    setLog([]);
    setPending([]);
    setRunning(false);
    onSession?.(null);
  }, [onSession]);

  return { session, log, pending, running, start, decide, resetForNewSession };
}
