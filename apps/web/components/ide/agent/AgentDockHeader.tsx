"use client";

export function AgentDockHeader({
  historyOpen,
  onToggleHistory,
  onNewSession,
  onOpenSettings,
  onCollapse,
  settingsRef,
}: {
  historyOpen: boolean;
  onToggleHistory: () => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
  onCollapse: () => void;
  settingsRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <div className="agent-dock-header">
      <span className="agent-dock-title">Agente</span>
      <div className="agent-dock-header-actions">
        <button type="button" className="icon-action-btn" title="Nova sessão" onClick={onNewSession}>
          +
        </button>
        <button
          type="button"
          className={`icon-action-btn${historyOpen ? " active" : ""}`}
          title="Histórico de sessões"
          onClick={onToggleHistory}
        >
          ⌕
        </button>
        <button
          ref={settingsRef}
          type="button"
          className="icon-action-btn"
          title="Personalizações"
          onClick={onOpenSettings}
        >
          ⚙
        </button>
        <button type="button" className="icon-action-btn" title="Recolher painel do agente" onClick={onCollapse}>
          «
        </button>
      </div>
    </div>
  );
}
