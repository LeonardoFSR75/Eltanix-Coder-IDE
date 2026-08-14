"use client";

import React, { useEffect, useState } from "react";
import { useTheme } from "@/lib/theme";
import { useIde } from "@/lib/ide-store";
import { getSandboxStats, type SandboxStats } from "@/lib/api/sandbox";
import type { LspStatus } from "@/lib/use-lsp";

interface StatusBarProps {
  lspStatus: LspStatus;
  cursorPosition?: { line: number; column: number };
}

/** Ícone de sol — modo claro */
function SunIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

/** Ícone de lua — modo escuro */
function MoonIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

/** Separador vertical */
function Sep() {
  return <span className="statusbar-sep" aria-hidden />;
}

function SandboxStatusItem({ sessionId }: { sessionId: string }) {
  const [stats, setStats] = useState<SandboxStats | null>(null);

  useEffect(() => {
    let ativo = true;
    const load = async () => {
      try {
        const s = await getSandboxStats(sessionId);
        if (ativo && s) setStats(s);
      } catch {
        // Ignora
      }
    };
    void load();
    const timer = setInterval(load, 4000);
    return () => {
      ativo = false;
      clearInterval(timer);
    };
  }, [sessionId]);

  if (!stats || stats.status === "unavailable") return null;

  const portas = stats.ports?.length ? ` :${stats.ports.join(", ")}` : "";
  const mem = stats.metrics?.memory_mb ? ` · ${stats.metrics.memory_mb}MB` : "";

  return (
    <span
      className="statusbar-item"
      title={`Sandbox Docker (${stats.name || sessionId})\nStatus: ${stats.status}\nPortas: ${stats.ports?.join(", ") || "nenhuma"}\nRAM: ${stats.metrics?.memory_mb ?? 0}MB / ${stats.metrics?.memory_limit_mb ?? 2048}MB`}
      style={{ color: stats.ports?.length ? "var(--accent-emerald, #34d399)" : "var(--text-dim)" }}
    >
      <span className={`pulse-dot ${stats.ports?.length ? "ok" : ""}`} />
      Sandbox{portas}{mem}
    </span>
  );
}

export function StatusBar({ lspStatus, cursorPosition }: StatusBarProps) {
  const { project, projects, routerLatency, routerStatus, activeSessionId } = useIde();
  const { theme, toggleTheme } = useTheme();

  const activeProjObj = projects.find((p) => p.name === project);

  return (
    <footer className="ide-statusbar">
      <div className="statusbar-left">
        <span className="statusbar-item branch-item" title="Branch Git ativo">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="6" y1="3" x2="6" y2="15" />
            <circle cx="18" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M18 9a9 9 0 0 1-9 9" />
          </svg>
          {activeProjObj?.branch ?? "main*"}
        </span>
        <Sep />

        <span className="statusbar-item diag-item" title="Problemas e Diagnósticos">
          0 🚨 0 ⚠️
        </span>
        <Sep />

        <span
          className={`statusbar-item router-item ${routerStatus}`}
          title="Status de conexão com o Gateway Router de IA"
        >
          <span className={`pulse-dot ${routerStatus === "online" ? "ok" : "err"}`} />
          Router:{" "}
          <strong style={{ color: routerStatus === "online" ? "var(--accent-emerald)" : "var(--danger)" }}>
            {routerLatency !== null ? `${routerLatency}ms` : routerStatus}
          </strong>
        </span>

        {lspStatus.language && (
          <>
            <Sep />
            <span
              className={`statusbar-item lsp-item ${lspStatus.ready ? "ok" : lspStatus.error ? "err" : "loading"}`}
              title={lspStatus.error || `LSP ativo: ${lspStatus.language}`}
            >
              <span className={`pulse-dot ${lspStatus.ready ? "ok" : lspStatus.error ? "err" : ""}`} />
              {lspStatus.ready ? `LSP: ${lspStatus.language}` : `LSP (${lspStatus.language}...)`}
            </span>
          </>
        )}

        {activeSessionId && (
          <>
            <Sep />
            <SandboxStatusItem sessionId={activeSessionId} />
          </>
        )}
      </div>

      <div className="statusbar-right">
        {cursorPosition && (
          <>
            <span className="statusbar-item cursor-item" title="Posição do cursor">
              Ln {cursorPosition.line}, Col {cursorPosition.column}
            </span>
            <Sep />
          </>
        )}

        <span className="statusbar-item" title="Codificação do arquivo">
          UTF-8
        </span>
        <Sep />
        <span className="statusbar-item" title="Indentação">
          Espaços: 2
        </span>
        <Sep />

        <button
          type="button"
          className="statusbar-theme-btn"
          onClick={toggleTheme}
          title={`Trocar para modo ${theme === "dark" ? "claro" : "escuro"}`}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          {theme === "dark" ? "Light" : "Dark"}
        </button>
      </div>
    </footer>
  );
}
