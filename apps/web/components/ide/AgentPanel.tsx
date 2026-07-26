"use client";

import { useCallback, useRef, useState } from "react";
import { post, streamEvents } from "@/lib/client";
import { useIde } from "@/lib/ide-store";

type Mode = "ask" | "edit" | "agent";

interface PendingAction {
  tool_call_id: string;
  tool: string;
  risk: string;
  arguments: Record<string, unknown>;
  summary: string;
}

interface Session {
  session_id: string;
  branch: string;
  worktree_path: string;
  sandbox_available: boolean;
  sandbox_error: string | null;
  github_available: boolean;
  warnings: string[];
}

interface LogLine {
  kind: "info" | "assistant" | "tool" | "error" | "cost";
  text: string;
}

const MODE_HINT: Record<Mode, string> = {
  ask: "Só leitura: o agente responde sem tocar em nada.",
  edit: "Pode editar arquivos, mas não executar comandos.",
  agent: "Pode editar, executar testes e abrir PR. Cada ação de risco pede aprovação.",
};

export function AgentPanel({
  onFileTouched,
  onSession,
}: {
  onFileTouched?: (path: string) => void;
  onSession?: (sessionId: string | null) => void;
}) {
  const { project } = useIde();
  const [task, setTask] = useState("");
  const [mode, setMode] = useState<Mode>("agent");
  const [session, setSession] = useState<Session | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

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

      // O grafo parou pedindo aprovação: mostramos as ações e esperamos.
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

  const start = useCallback(async () => {
    if (!task.trim()) return;
    setLog([]);
    setPending([]);
    try {
      const created = await post<Session>("/api/agent/sessions", { task, mode, project });
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
  }, [task, mode, project, append, run, onSession]);

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

  return (
    <div className="agent">
      <div className="agent-controls">
        <div className="mode-row">
          {(["ask", "edit", "agent"] as Mode[]).map((option) => (
            <button
              key={option}
              type="button"
              className={`mode${mode === option ? " active" : ""}`}
              onClick={() => setMode(option)}
              disabled={running}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="mode-hint">{MODE_HINT[mode]}</div>

        <textarea
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="O que o agente deve fazer? Ex.: adicionar tratamento de rate limit no adaptador Databricks, com testes."
          rows={4}
          disabled={running}
        />
        <button type="button" className="primary" onClick={() => void start()} disabled={running || !task.trim() || !project}>
          {running ? "trabalhando…" : "iniciar"}
        </button>
      </div>

      {session && (
        <div className="agent-meta">
          <span className="pill">{session.branch || "sem branch"}</span>
          <span className={`pill ${session.sandbox_available ? "ok" : "warn"}`}>
            sandbox {session.sandbox_available ? "ativo" : "indisponível"}
          </span>
          <span className={`pill ${session.github_available ? "ok" : ""}`}>
            github {session.github_available ? "ok" : "off"}
          </span>
        </div>
      )}

      {pending.length > 0 && (
        <div className="approval">
          <div className="approval-title">
            O agente quer executar {pending.length} ação{pending.length > 1 ? "ões" : ""}:
          </div>
          <ul>
            {pending.map((action) => (
              <li key={action.tool_call_id}>
                <span className={`pill ${action.risk === "exec" ? "bad" : "warn"}`}>{action.risk}</span>{" "}
                {action.summary}
              </li>
            ))}
          </ul>
          <div className="approval-actions">
            <button type="button" className="primary" onClick={() => void decide(true)}>
              aprovar
            </button>
            <button type="button" onClick={() => void decide(false)}>
              recusar
            </button>
          </div>
        </div>
      )}

      <div className="agent-log">
        {log.map((line, index) => (
          <div key={index} className={`log-line ${line.kind}`}>
            {line.text}
          </div>
        ))}
        {log.length === 0 && <div className="tree-hint">Nenhuma sessão iniciada.</div>}
      </div>
    </div>
  );
}
