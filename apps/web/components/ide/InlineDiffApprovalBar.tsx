"use client";

import React from "react";

interface InlineDiffApprovalBarProps {
  onAccept: () => void;
  onReject: () => void;
  onToggleSideBySide?: () => void;
  isSideBySide?: boolean;
  busy?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function InlineDiffApprovalBar({
  onAccept,
  onReject,
  onToggleSideBySide,
  isSideBySide,
  busy = false,
  className = "",
  style,
}: InlineDiffApprovalBarProps) {
  return (
    <div className={`inline-approval-bar ${className}`} style={style}>
      <button
        type="button"
        className="inline-accept-btn"
        onClick={onAccept}
        disabled={busy}
        title="Aceitar alterações (Alt+Enter)"
      >
        <span>Accept</span>
        <kbd className="kbd-shortcut">Alt+↵</kbd>
      </button>

      <button
        type="button"
        className="inline-reject-btn"
        onClick={onReject}
        disabled={busy}
        title="Rejeitar alterações (Shift+Alt+Backspace)"
      >
        <span>Reject</span>
        <kbd className="kbd-shortcut">Shift+Alt+⌫</kbd>
      </button>

      {onToggleSideBySide && (
        <button
          type="button"
          className="inline-toggle-btn"
          onClick={onToggleSideBySide}
          title={isSideBySide ? "Alternar para visualização Inline" : "Alternar para visualização Lado a Lado"}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
          </svg>
        </button>
      )}
    </div>
  );
}
