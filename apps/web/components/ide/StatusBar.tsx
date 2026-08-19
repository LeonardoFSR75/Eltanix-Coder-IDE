"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTheme } from "@/lib/theme";
import { useIde } from "@/lib/ide-store";
import { toggleWebApp } from "@/lib/api/sandbox";
import { getProjectPackages, resolvePackagesSyncStatus, type PackagesSyncStatus } from "@/lib/api/packages";
import type { LspStatus } from "@/lib/use-lsp";
import { refreshSandboxStats, useSandboxStats } from "@/lib/use-sandbox-stats";

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
  // Poller compartilhado com o painel de navegador central — ver comentário
  // em `lib/use-sandbox-stats.ts` (item 14 do plano de robustez do
  // navegador interno).
  const stats = useSandboxStats(sessionId);
  const [isPrewarming, setIsPrewarming] = useState(false);
  const { openFile } = useIde();

  const handleTogglePrewarm = async () => {
    setIsPrewarming(true);
    try {
      await toggleWebApp(sessionId, true);
      await refreshSandboxStats(sessionId);
    } catch {
      // Ignora
    } finally {
      setIsPrewarming(false);
    }
  };

  if (!stats || stats.status === "unavailable") {
    return (
      <button
        type="button"
        className="statusbar-item"
        onClick={() => void handleTogglePrewarm()}
        title="Clique para aquecer o Sandbox e o Navegador em segundo plano"
        style={{ cursor: "pointer", background: "none", border: "none", color: "inherit" }}
      >
        🌐 Web App: {isPrewarming ? "Aquecendo..." : "Ligar Pre-warm"}
      </button>
    );
  }

  const mem = stats.metrics?.memory_mb ? ` · ${stats.metrics.memory_mb}MB` : "";

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span
        className="statusbar-item"
        title={`Sandbox Docker (${stats.name || sessionId})\nStatus: ${stats.status}\nPortas: ${stats.ports?.join(", ") || "nenhuma"}\nRAM: ${stats.metrics?.memory_mb ?? 0}MB / ${stats.metrics?.memory_limit_mb ?? 2048}MB`}
        style={{ color: stats.status === "running" ? "var(--accent-emerald, #34d399)" : "var(--text-dim)" }}
      >
        <span className={`pulse-dot ${stats.status === "running" ? "ok" : ""}`} />
        Sandbox {stats.status === "running" ? "Online" : stats.status}{mem}
      </span>
      {stats.ports?.map((porta) => (
        <button
          key={porta}
          type="button"
          className="statusbar-item"
          title={`Abrir localhost:${porta} no Navegador Central (modo Agente — a porta do sandbox só é alcançável pelo serviço de navegador, nunca por um iframe direto)`}
          // Modo Agente, não Live: a porta do sandbox só entra na rede
          // `browser_net` (nunca publicada no host) — um iframe apontado
          // pra `localhost:<porta>` falharia sempre. O serviço de
          // navegador sabe resolver via `sicoobito-<sessionId>:<porta>`.
          onClick={() => openFile(`browser-agent:http://localhost:${porta}`)}
          style={{
            cursor: "pointer",
            background: "rgba(56, 189, 248, 0.15)",
            color: "#38bdf8",
            border: "1px solid rgba(56, 189, 248, 0.4)",
            borderRadius: 3,
            padding: "1px 6px",
            fontSize: "10.5px",
            fontWeight: 500,
          }}
        >
          🌐 :{porta} ↗
        </button>
      ))}
    </div>
  );
}

const SYNC_LABEL: Record<PackagesSyncStatus, string> = {
  ok: "Pacotes sincronizados",
  warning: "Pacotes fora do manifesto",
  idle: "Sem pacotes instalados",
};

function PackagesStatusItem({ project }: { project: string }) {
  const { setPanel, sidebarOpen, toggleSidebar } = useIde();
  const [status, setStatus] = useState<PackagesSyncStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getProjectPackages(project);
      setStatus(resolvePackagesSyncStatus(data.packages, data.requirements_map ?? {}));
    } catch {
      setStatus(null);
    }
  }, [project]);

  useEffect(() => {
    void load();
  }, [load]);

  // Mesmo evento disparado por `sessionRuntime.ts` (tool `manage_packages` do
  // agente) e por `PackagesPanel` (instalar/remover/sincronizar pelo próprio
  // usuário) — este indicador não faz polling próprio, só reage a ele.
  useEffect(() => {
    const handleChanged = () => void load();
    window.addEventListener("sicoobito:packages:changed", handleChanged);
    return () => window.removeEventListener("sicoobito:packages:changed", handleChanged);
  }, [load]);

  if (!status) return null;

  return (
    <button
      type="button"
      className="statusbar-item"
      title={SYNC_LABEL[status]}
      onClick={() => {
        if (!sidebarOpen) toggleSidebar();
        setPanel("packages");
      }}
      style={{ cursor: "pointer", background: "none", border: "none", color: "inherit" }}
    >
      <span
        className={`pulse-dot ${status === "ok" ? "ok" : status === "warning" ? "err" : ""}`}
      />
      {status === "warning" ? "⚠️" : "📦"} {SYNC_LABEL[status]}
    </button>
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

        <span className="statusbar-item diag-item" title="Problemas e Diagnósticos do arquivo ativo">
          {lspStatus.errorCount} 🚨 {lspStatus.warningCount} ⚠️
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

        {project && (
          <>
            <Sep />
            <PackagesStatusItem project={project} />
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
