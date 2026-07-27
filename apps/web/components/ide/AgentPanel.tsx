"use client";

/**
 * Visão de log e aprovação de uma sessão do agente.
 *
 * Não é dono do estado — quem chama `useAgentSession` é o `AgentDock`, que
 * repassa aqui só o que precisa ser mostrado. Isolar isto permite que o
 * cabeçalho, o histórico e o input do chat mudem de layout sem duplicar a
 * lógica de streaming/aprovação.
 */

import { useToast } from "@/components/Toast";
import type { LogLine, PendingAction, Session } from "./agent/useAgentSession";

export function AgentPanel({
  session,
  log,
  pending,
  onDecide,
}: {
  session: Session | null;
  log: LogLine[];
  pending: PendingAction[];
  onDecide: (approved: boolean) => void;
}) {
  const { toast } = useToast();

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast("Código copiado para a área de transferência!", "success");
  };

  return (
    <div className="agent-log-wrap">
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
            <button type="button" className="primary" onClick={() => onDecide(true)}>
              aprovar
            </button>
            <button type="button" onClick={() => onDecide(false)}>
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
