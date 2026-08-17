"use client";

/**
 * Fase 7 da auditoria UX/DX — visão consolidada de uma orquestração
 * multiagente. Agrega componentes JÁ EXISTENTES (plano, atividade ao vivo,
 * aprovação granular, arquivos alterados, terminal, navegador, histórico)
 * num grid só, sem duplicar nenhuma lógica de sessão: recebe o runtime que
 * `useAgentSessions` (AgentDock.tsx) já instanciou, nunca cria um novo — daí
 * as props virem prontas em vez de um `sessionId` que o componente resolveria
 * sozinho.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { AgentLiveActivity, ApprovalCard } from "@/components/ide/AgentPanel";
import { EditorBrowserView } from "@/components/ide/EditorBrowserView";
import { TerminalPanel } from "@/components/ide/Terminal";
import { AgentManager } from "@/components/ide/agent/AgentManager";
import { TodoCard } from "@/components/ide/agent/cards";
import type { AgentSessionRuntime } from "@/components/ide/agent/sessionRuntime";
import type { SessionSummary } from "@/components/ide/agent/sessionTypes";
import { getSessionDiff, type SessionDiff } from "@/lib/api/agent";

export function MissionControl({
  project,
  sessions,
  activeId,
  active,
  sessionsVersion,
  switchTo,
  openClosedSession,
  onClose,
}: {
  project: string | null;
  sessions: SessionSummary[];
  activeId: string | null;
  active: AgentSessionRuntime | null;
  sessionsVersion: number;
  switchTo: (sessionId: string) => void;
  openClosedSession: (sessionId: string, task: string) => void;
  onClose: () => void;
}) {
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [diff, setDiff] = useState<SessionDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  const sessionId = active?.session?.session_id ?? null;
  // `active?.pending` só troca de referência quando o runtime de fato recebe
  // uma lista nova (ver sessionRuntime.ts) — memoizar aqui evita recriar um
  // array `[]` a cada render (o efeito abaixo entraria em loop resetando
  // `decisions`, já que cada novo array dispara o efeito, que causa um
  // re-render, que cria outro array novo).
  const pending = useMemo(
    () => (active?.readOnly ? [] : (active?.pending ?? [])),
    [active?.readOnly, active?.pending],
  );

  useEffect(() => {
    setDecisions({});
  }, [pending]);

  const loadDiff = useCallback(() => {
    if (!sessionId) {
      setDiff(null);
      setDiffError(null);
      return;
    }
    setDiffLoading(true);
    setDiffError(null);
    getSessionDiff(sessionId)
      .then((result) => setDiff(result))
      .catch((error) => setDiffError(error instanceof Error ? error.message : String(error)))
      .finally(() => setDiffLoading(false));
  }, [sessionId]);

  useEffect(() => {
    loadDiff();
  }, [loadDiff]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const isThinking = Boolean(active?.running) && pending.length === 0;

  // Renderizado num portal para `document.body`: AgentDock (o pai real) fica
  // dentro do dock lateral redimensionável, cujo wrapper cria um contexto de
  // posicionamento próprio — sem o portal, `position: fixed` do overlay fica
  // preso à largura do dock (~360px) em vez de cobrir a viewport inteira.
  return createPortal(
    <div
      className="mission-control-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="mission-control" role="dialog" aria-label="Mission Control">
        <header className="mission-control-header">
          <div className="mission-control-title-group">
            <h2>🚀 Mission Control</h2>
            <span className="mission-control-subtitle">
              {active?.task || "Nenhuma sessão ativa"}
              {project ? ` · ${project}` : ""}
            </span>
          </div>
          <button
            type="button"
            className="mission-control-close"
            onClick={onClose}
            aria-label="Fechar Mission Control"
            title="Fechar (Esc)"
          >
            ✕
          </button>
        </header>

        <div className="mission-control-grid">
          <section className="mission-control-cell mission-control-plan">
            <h3>Plano</h3>
            <TodoCard todos={active?.todos ?? []} />
          </section>

          <section className="mission-control-cell mission-control-activity">
            <h3>Atividade ao vivo</h3>
            {isThinking ? (
              <AgentLiveActivity
                activity={active?.currentActivity ?? null}
                recentActivities={active?.recentActivities ?? []}
              />
            ) : (
              <p className="mission-control-empty-note">Sem atividade em andamento.</p>
            )}
          </section>

          <section className="mission-control-cell mission-control-approval">
            <h3>Aprovação pendente</h3>
            {pending.length > 0 ? (
              <ApprovalCard
                pending={pending}
                decisions={decisions}
                running={active?.running}
                onDecide={(next) => void active?.decide(next)}
                onDecision={(toolCallId, approved) =>
                  setDecisions((prev) => ({ ...prev, [toolCallId]: approved }))
                }
              />
            ) : (
              <p className="mission-control-empty-note">Nada aguardando aprovação.</p>
            )}
          </section>

          <section className="mission-control-cell mission-control-diff">
            <h3>
              Arquivos alterados
              <button
                type="button"
                className="mission-control-refresh"
                onClick={loadDiff}
                title="Recarregar arquivos alterados"
                aria-label="Recarregar arquivos alterados"
              >
                ↻
              </button>
            </h3>
            {diffLoading ? (
              <p className="mission-control-empty-note">Carregando…</p>
            ) : diffError ? (
              <p className="mission-control-empty-note">{diffError}</p>
            ) : diff && diff.files.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Arquivo</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diff.files.map((file) => (
                      <tr key={file.path}>
                        <td>{file.path}</td>
                        <td>{file.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mission-control-empty-note">
                {sessionId ? "Sem alterações no worktree." : "Sem sessão ativa."}
              </p>
            )}
          </section>

          <section className="mission-control-cell mission-control-browser">
            <h3>Navegador</h3>
            {sessionId ? (
              <EditorBrowserView sessionId={sessionId} />
            ) : (
              <p className="mission-control-empty-note">Sem sessão ativa para inspecionar.</p>
            )}
          </section>

          <section className="mission-control-cell mission-control-terminal">
            <h3>Terminal</h3>
            <TerminalPanel sessionId={sessionId} project={project} />
          </section>

          <section className="mission-control-cell mission-control-history">
            <h3>Histórico de sessões</h3>
            <AgentManager
              project={project}
              refreshKey={sessionsVersion}
              liveSessions={sessions}
              activeId={activeId}
              onOpenLive={switchTo}
              onOpenClosed={openClosedSession}
              onClose={onClose}
            />
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}
