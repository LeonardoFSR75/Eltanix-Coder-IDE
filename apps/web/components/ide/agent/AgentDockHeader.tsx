"use client";

import React from "react";
import type { RuntimeStatus } from "./sessionTypes";

/**
 * Cabeçalho do Dock do Agente — estilo GitHub Copilot Chat.
 *
 * Layout: [🤖 Copilot · status · branch] ............. [+ Nova] [📜] [⚙] [«]
 */
const STATUS_META: Record<RuntimeStatus, { label: string; className: string }> = {
  idle: { label: "Ocioso", className: "idle" },
  running: { label: "Executando", className: "running" },
  awaiting_approval: { label: "Aguardando aprovação", className: "awaiting-approval" },
  done: { label: "Concluído", className: "done" },
  error: { label: "Erro", className: "error" },
  closed: { label: "Encerrada (leitura)", className: "closed" },
};

export function AgentDockHeader({
  historyOpen,
  onToggleHistory,
  onNewSession,
  onOpenSettings,
  onCollapse,
  settingsRef,
  status,
  branch,
  onOpenGit,
}: {
  historyOpen: boolean;
  onToggleHistory: () => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
  onCollapse: () => void;
  settingsRef: React.RefObject<HTMLButtonElement | null>;
  /** Status da sessão ativa no dock — `undefined` quando nenhuma sessão existe ainda. */
  status?: RuntimeStatus;
  /** Branch git da sessão ativa, se houver uma sessão com worktree. */
  branch?: string | null;
  onOpenGit?: () => void;
}) {
  const meta = status ? STATUS_META[status] : null;

  return (
    <div className="agent-dock-header">
      <div className="agent-dock-title-wrap">
        {/* Copilot-style icon */}
        <div className="copilot-icon-wrap">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <defs>
              <linearGradient id="copilot-g" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#38bdf8" />
                <stop offset="100%" stopColor="#a78bfa" />
              </linearGradient>
            </defs>
            <path
              d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14h-1v-4h2v4zm4 0h-2v-6h2v6zm-6-8V7h6v1H9z"
              fill="url(#copilot-g)"
            />
            <circle cx="12" cy="12" r="3" fill="url(#copilot-g)" opacity="0.6" />
          </svg>
        </div>
        <span className="agent-dock-title">NovaAI Studio Agente</span>
        <span
          className={`copilot-status-dot${meta ? ` ${meta.className}` : ""}`}
          title={meta ? `Agente: ${meta.label}` : "Nenhuma sessão ativa"}
        />
        {branch && (
          <button
            type="button"
            className="agent-dock-branch-chip"
            title={`Branch da sessão ativa: ${branch} — abrir painel Git`}
            onClick={onOpenGit}
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
            {branch}
          </button>
        )}
      </div>

      <div className="agent-dock-header-actions">
        <button
          type="button"
          className="dock-action-btn"
          title="Nova Sessão (Ctrl+Shift+N)"
          onClick={onNewSession}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>

        <button
          type="button"
          className={`dock-action-btn${historyOpen ? " active" : ""}`}
          title="Histórico de Sessões"
          onClick={onToggleHistory}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </button>

        <button
          ref={settingsRef}
          type="button"
          className="dock-action-btn"
          title="Configurações & Provedores LLM"
          onClick={onOpenSettings}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>

        <button
          type="button"
          className="dock-action-btn"
          title="Recolher Painel"
          onClick={onCollapse}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      </div>
    </div>
  );
}
