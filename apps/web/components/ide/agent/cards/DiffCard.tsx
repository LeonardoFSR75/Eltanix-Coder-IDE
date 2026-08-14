"use client";

import { useState } from "react";
import { autoDetectLanguage, DiffView } from "@/components/ide/Editor";
import { acceptFile, revertFile } from "@/lib/api/agent";
import { useIde } from "@/lib/ide-store";
import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

type Decision = "pending" | "accepted" | "rejected";

// Toda chamada de write_file/edit_file grava no worktree isolado da sessão.
// "Aceitar" chama o endpoint accept para copiar o arquivo do worktree para o
// workspace principal do usuário e notifica a IDE. "Rejeitar" chama o
// endpoint de revert.
export function DiffCard({
  tool,
  content,
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
  const existed = data.existed !== false;
  const verb = tool === "write_file" ? "escrever" : "editar";
  const language = autoDetectLanguage(path);
  const riskLevel = riskLevelForTool(tool);

  // A ferramenta pode ter falhado (arquivo não encontrado, trecho ambíguo
  // etc.) — sem `path`, não há diff nenhum para revisar, só o erro.
  if (!ok || !path) {
    return (
      <ToolCardShell icon="✏️" title={`${verb} — falhou`} riskLevel={riskLevel} ok={false} defaultOpen>
        <pre className="tool-card-pre">{content}</pre>
      </ToolCardShell>
    );
  }

  const accept = async () => {
    if (!sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await acceptFile(sessionId, path);
      setDecision("accepted");
      notifyFileChanged(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await revertFile(sessionId, path, before, existed);
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
      riskLevel={riskLevel}
      ok={ok}
      defaultOpen
      bodyClassName="tool-card-body-diff"
    >
      <div className="diff-card-view">
        <DiffView
          original={decision === "rejected" ? after : before}
          modified={decision === "rejected" ? before : after}
          language={language}
          showApprovalBar={false}
          busy={busy}
        />
      </div>

      <div className="diff-card-actions">
        {decision === "pending" && (
          <>
            <button
              type="button"
              className="diff-card-btn accept"
              disabled={busy || !sessionId}
              onClick={() => void accept()}
              title={sessionId ? "Aplicar esta edição no workspace" : "Sessão indisponível"}
            >
              {busy ? "aplicando…" : "✓ Aceitar"}
            </button>
            <button
              type="button"
              className="diff-card-btn reject"
              disabled={busy || !sessionId}
              onClick={() => void reject()}
              title={sessionId ? "Reverter esta edição" : "Sessão indisponível"}
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
