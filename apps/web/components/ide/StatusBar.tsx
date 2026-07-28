"use client";

import React from "react";
import { useTheme } from "@/lib/theme";
import { useIde } from "@/lib/ide-store";
import type { LspStatus } from "@/lib/use-lsp";

interface StatusBarProps {
  lspStatus: LspStatus;
  cursorPosition?: { line: number; column: number };
}

export function StatusBar({ lspStatus, cursorPosition }: StatusBarProps) {
  const { project, projects, routerLatency, routerStatus } = useIde();
  const { theme, toggleTheme } = useTheme();

  const activeProjObj = projects.find((p) => p.name === project);

  return (
    <footer className="ide-statusbar">
      <div className="statusbar-left">
        {activeProjObj?.is_git && (
          <span className="statusbar-item branch-item" title="Branch Git ativo">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
            {activeProjObj.branch ?? "—"}
          </span>
        )}

        <span
          className={`statusbar-item router-item ${routerStatus}`}
          title="Status de conexão com o Gateway Router de IA"
        >
          <span className={`pulse-dot ${routerStatus === "online" ? "ok" : "err"}`} />
          Router: {routerLatency !== null ? `${routerLatency}ms` : routerStatus}
        </span>

        {lspStatus.language && (
          <span
            className={`statusbar-item lsp-item ${lspStatus.ready ? "ok" : lspStatus.error ? "err" : "loading"}`}
            title={lspStatus.error || `LSP ativo: ${lspStatus.language}`}
          >
            <span className={`pulse-dot ${lspStatus.ready ? "ok" : lspStatus.error ? "err" : ""}`} />
            {lspStatus.ready ? `LSP: ${lspStatus.language}` : `LSP (${lspStatus.language}...)`}
          </span>
        )}
      </div>

      <div className="statusbar-right">
        {cursorPosition && (
          <span className="statusbar-item cursor-item">
            Ln {cursorPosition.line}, Col {cursorPosition.column}
          </span>
        )}

        <span className="statusbar-item">UTF-8</span>
        <span className="statusbar-item">Spaces: 2</span>

        <button
          type="button"
          className="statusbar-theme-btn"
          onClick={toggleTheme}
          title={`Trocar para modo ${theme === "dark" ? "claro" : "escuro"}`}
        >
          {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
        </button>
      </div>
    </footer>
  );
}
