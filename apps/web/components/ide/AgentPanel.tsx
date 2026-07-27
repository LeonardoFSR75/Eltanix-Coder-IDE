"use client";

import { useCallback, useRef, useState } from "react";
import { post, streamEvents } from "@/lib/client";
import { useIde } from "@/lib/ide-store";
import { useToast } from "@/components/Toast";

type Mode = "ask" | "edit" | "agent" | "plan" | "auto";

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
  agent: "Agente interativo: edita e roda testes pedindo aprovação.",
  plan: "Modo Planejar: gera um plano passo a passo detalhado antes de alterar arquivos.",
  auto: "Modo Automático: executa tarefas ponta a ponta autonomamente (edição, testes e fixes).",
};

const PRESET_PROMPTS = [
  { label: "💡 Explicar", prompt: "Explicar a arquitetura e o funcionamento do código deste projeto." },
  { label: "⚡ Refatorar", prompt: "Refatorar o código do módulo para melhorar legibilidade e modularidade." },
  { label: "🧪 Testes", prompt: "Escrever suíte de testes unitários cobrindo cenários e limites." },
  { label: "🐞 Bugs", prompt: "Analisar e corrigir eventuais falhas, exceções ou gargalos de memória." },
  { label: "📋 Plano", prompt: "Criar um plano de execução detalhado para a implementação." },
];

export function AgentPanel({
  onFileTouched,
  onSession,
}: {
  onFileTouched?: (path: string) => void;
  onSession?: (sessionId: string | null) => void;
}) {
  const { project, active } = useIde();
  const { toast } = useToast();
  const [task, setTask] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const append = useCallback((line: LogLine) => {
    setLog((prev) => [...prev, line]);
  }, []);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast("Código copiado para a área de transferência!", "success");
  };

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
        {/* Seletor Duplo Principal de Modo */}
        <div className="dual-mode-wrap" style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <button
            type="button"
            className={`mode-btn-large ${mode === "auto" || mode === "agent" || mode === "plan" || mode === "edit" ? "active" : ""}`}
            onClick={() => setMode("auto")}
            disabled={running}
            style={{ flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8, cursor: "pointer" }}
          >
            ⚡ Agente Autônomo
          </button>
          <button
            type="button"
            className={`mode-btn-large ${mode === "ask" ? "active" : ""}`}
            onClick={() => setMode("ask")}
            disabled={running}
            style={{ flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8, cursor: "pointer" }}
          >
            ❓ Pergunta & Leitura
          </button>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span className="mode-hint" style={{ fontSize: 12, color: "var(--text-dim)" }}>{MODE_HINT[mode]}</span>
          <button
            type="button"
            className="text-btn"
            style={{ fontSize: 11, background: "none", border: "none", color: "var(--accent)", cursor: "pointer" }}
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "Esconder avançados ▲" : "Modos avançados ▼"}
          </button>
        </div>

        {showAdvanced && (
          <div className="mode-row" style={{ marginBottom: 10 }}>
            {(["plan", "auto", "ask", "edit", "agent"] as Mode[]).map((option) => (
              <button
                key={option}
                type="button"
                className={`mode${mode === option ? " active" : ""}`}
                onClick={() => setMode(option)}
                disabled={running}
              >
                {option === "plan" ? "📋 planejar" : option === "auto" ? "⚡ auto" : option}
              </button>
            ))}
          </div>
        )}

        <div className="agent-presets">
          {PRESET_PROMPTS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="preset-chip"
              disabled={running}
              onClick={() => setTask(p.prompt)}
            >
              {p.label}
            </button>
          ))}
        </div>

        <textarea
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="O que o agente deve fazer? Ex.: refatorar função e criar testes."
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
            <div className="log-line-content">{line.text}</div>
            {line.kind === "assistant" && (
              <div className="log-line-actions" style={{ marginTop: 4, display: "flex", gap: 6 }}>
                <button
                  type="button"
                  className="log-btn"
                  style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, cursor: "pointer" }}
                  onClick={() => copyToClipboard(line.text)}
                >
                  📋 Copiar
                </button>
              </div>
            )}
          </div>
        ))}
        {log.length === 0 && <div className="tree-hint">Nenhuma sessão iniciada.</div>}
      </div>
    </div>
  );
}
