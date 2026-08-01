"use client";

import { useState } from "react";
import { autoDetectLanguage, DiffView } from "@/components/ide/Editor";
import { post } from "@/lib/client";
import { useIde } from "@/lib/ide-store";
import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

type Decision = "pending" | "accepted" | "rejected";

// Toda chamada de write_file/edit_file já grava no worktree isolado da
// sessão antes de chegar aqui (fluxo escreve-então-revisa). "Aceitar" não
// precisa de ação nenhuma — a mudança já está lá. "Rejeitar" chama o
// endpoint de revert, que devolve o arquivo ao estado anterior no worktree
// via `git checkout` (ou remove, se o arquivo era novo).
export function DiffCard({
  tool,
  data,
  ok,
  sessionId,
}: ToolCardProps & { sessionId: string | null }) {
  const { notifyFileChanged } = useIde();
  const [decision, setDecision] = useState<Decision>("pending");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const path = String(data.path ?? "");
  const before = String(data.before ?? "");
  const after = String(data.after ?? "");
  const verb = tool === "write_file" ? "escrever" : "editar";
  const language = autoDetectLanguage(path);

  const reject = async () => {
    if (!sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/api/agent/sessions/${sessionId}/files/revert`, { path });
      setDecision("rejected");
      notifyFileChanged(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ToolCardShell
      icon="✏️"
      title={`${verb} ${path}`}
      ok={ok}
      defaultOpen
      bodyClassName="tool-card-body-diff"
    >
      <div className="diff-card-view">
        <DiffView
          original={decision === "rejected" ? after : before}
          modified={decision === "rejected" ? before : after}
          language={language}
        />
      </div>
      <div className="diff-card-actions">
        {decision === "pending" && (
          <>
            <button
              type="button"
              className="diff-card-btn accept"
              onClick={() => setDecision("accepted")}
            >
              ✓ Aceitar
            </button>
            <button
              type="button"
              className="diff-card-btn reject"
              disabled={busy || !sessionId}
              onClick={() => void reject()}
              title={sessionId ? "Reverter esta edição no worktree" : "Sessão indisponível"}
            >
              {busy ? "revertendo…" : "✕ Rejeitar"}
            </button>
          </>
        )}
        {decision === "accepted" && <span className="diff-card-status accepted">✓ mantido</span>}
        {decision === "rejected" && <span className="diff-card-status rejected">✕ revertido</span>}
      </div>
      {error && <div className="diff-card-error">{error}</div>}
    </ToolCardShell>
  );
}
