"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Editor } from "@/components/ide/Editor";
import { AgentDock } from "@/components/ide/agent/AgentDock";
import { Explorer, GitPanel, SearchPanel } from "@/components/ide/Panels";
import { CommandPalette, QuickOpen, type Command } from "@/components/ide/Overlays";
import { TerminalPanel } from "@/components/ide/Terminal";
import { StatusBar } from "@/components/ide/StatusBar";
import { IdeProvider, useIde, type PanelId } from "@/lib/ide-store";

function Shell() {
  const ide = useIde();
  const [overlay, setOverlay] = useState<"quick" | "palette" | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [cursorPos, setCursorPos] = useState<{ line: number; column: number }>({ line: 1, column: 1 });
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [isResizingAgent, setIsResizingAgent] = useState(false);
  const [isResizingTerminal, setIsResizingTerminal] = useState(false);

  const comandos = useMemo<Command[]>(
    () => [
      { id: "quick", title: "Ir para arquivo…", shortcut: "Ctrl+P", run: () => setOverlay("quick") },
      { id: "explorer", title: "Mostrar Explorer", run: () => ide.setPanel("explorer") },
      { id: "search", title: "Buscar no projeto", shortcut: "Ctrl+Shift+F", run: () => ide.setPanel("search") },
      { id: "git", title: "Mostrar controle de versão", run: () => ide.setPanel("git") },
      { id: "agent", title: "Mostrar agente", run: () => ide.setAgentDockOpen(true) },
      { id: "toggle-sidebar", title: "Alternar barra lateral", shortcut: "Ctrl+B", run: () => ide.toggleSidebar() },
      {
        id: "toggle-agent-dock",
        title: "Alternar painel do agente",
        shortcut: "Ctrl+Shift+A",
        run: () => ide.toggleAgentDock(),
      },
      { id: "terminal", title: "Alternar terminal", shortcut: "Ctrl+`", run: () => ide.setTerminalOpen(!ide.terminalOpen) },
      { id: "close", title: "Fechar aba atual", shortcut: "Ctrl+W", run: () => ide.active && ide.closeTab(ide.active) },
      { id: "refresh", title: "Recarregar árvore de arquivos", run: () => ide.bumpRevision() },
      { id: "reload-projects", title: "Recarregar lista de projetos", run: () => void ide.reloadProjects() },
    ],
    [ide],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (!mod) return;

      if (event.key.toLowerCase() === "b") {
        event.preventDefault();
        ide.toggleSidebar();
      } else if (event.shiftKey && event.key.toLowerCase() === "p") {
        event.preventDefault();
        setOverlay("palette");
      } else if (event.shiftKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        ide.setPanel("search");
      } else if (event.shiftKey && event.key.toLowerCase() === "a") {
        event.preventDefault();
        ide.toggleAgentDock();
      } else if (event.key.toLowerCase() === "p") {
        event.preventDefault();
        setOverlay("quick");
      } else if (event.key === "`") {
        event.preventDefault();
        ide.setTerminalOpen(!ide.terminalOpen);
      } else if (event.key.toLowerCase() === "w" && ide.active) {
        event.preventDefault();
        ide.closeTab(ide.active);
      }
    },
    [ide],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onKeyDown]);

  // Resizing mouse move handlers
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizingSidebar) {
        const newWidth = Math.max(180, Math.min(600, e.clientX - 48));
        ide.setSidebarWidth(newWidth);
      } else if (isResizingAgent) {
        const newWidth = Math.max(280, Math.min(800, window.innerWidth - e.clientX - 48));
        ide.setAgentDockWidth(newWidth);
      } else if (isResizingTerminal) {
        const newHeight = Math.max(120, Math.min(600, window.innerHeight - e.clientY - 30));
        ide.setTerminalHeight(newHeight);
      }
    };

    const handleMouseUp = () => {
      setIsResizingSidebar(false);
      setIsResizingAgent(false);
      setIsResizingTerminal(false);
    };

    if (isResizingSidebar || isResizingAgent || isResizingTerminal) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizingSidebar, isResizingAgent, isResizingTerminal, ide]);

  const trilha = ide.active ? ide.active.split("/") : [];

  return (
    <div
      className="ide-container"
      style={
        {
          "--sidebar-w": `${ide.sidebarWidth}px`,
          "--agent-w": `${ide.agentDockWidth}px`,
          "--term-h": `${ide.terminalHeight}px`,
        } as React.CSSProperties
      }
    >
      <div className={`ide${ide.agentDockOpen ? " agent-dock-open" : ""}`}>
        <nav className="activity-bar">
          <button
            type="button"
            className={`activity${ide.panel === "explorer" && ide.sidebarOpen ? " active" : ""}`}
            title="Explorer (Arquivos)"
            onClick={() => {
              if (ide.panel === "explorer" && ide.sidebarOpen) ide.toggleSidebar();
              else ide.setPanel("explorer");
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
              <polyline points="13 2 13 9 20 9" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "search" && ide.sidebarOpen ? " active" : ""}`}
            title="Localizar & Substituir (Ctrl+Shift+F)"
            onClick={() => {
              if (ide.panel === "search" && ide.sidebarOpen) ide.toggleSidebar();
              else ide.setPanel("search");
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "git" && ide.sidebarOpen ? " active" : ""}`}
            title="Controle de Versão Git"
            onClick={() => {
              if (ide.panel === "git" && ide.sidebarOpen) ide.toggleSidebar();
              else ide.setPanel("git");
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
          </button>

          <button
            type="button"
            className="activity sidebar-toggle-btn"
            style={{ marginTop: "auto" }}
            title={`Alternar barra lateral (Ctrl+B)`}
            onClick={() => ide.toggleSidebar()}
          >
            {ide.sidebarOpen ? "«" : "»"}
          </button>
        </nav>

        {ide.sidebarOpen && (
          <aside className="ide-sidebar" style={{ width: ide.sidebarWidth }}>
            <div className="project-picker">
              <select
                value={ide.project ?? ""}
                onChange={(e) => ide.setProject(e.target.value)}
                title="Projeto aberto"
              >
                {ide.projects.length === 0 && <option value="">nenhum projeto</option>}
                {ide.projects.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}{p.branch ? ` · ${p.branch}` : ""}
                  </option>
                ))}
              </select>
            </div>
            {ide.projectsError && <div className="panel-error">{ide.projectsError}</div>}

            <div className="panel-title">
              {ide.panel === "explorer" ? "Explorer" : ide.panel === "search" ? "Busca & Substituição" : "Controle Git"}
            </div>
            {ide.panel === "explorer" && <Explorer />}
            {ide.panel === "search" && <SearchPanel />}
            {ide.panel === "git" && <GitPanel />}
          </aside>
        )}

        {ide.sidebarOpen && (
          <div
            className="resizer-handle resizer-sidebar"
            onMouseDown={() => setIsResizingSidebar(true)}
            title="Arrastar para redimensionar barra lateral"
          />
        )}

        <main className="ide-main">
          <div className="tabs">
            {ide.tabs.map((tab) => (
              <div key={tab} className={`tab${ide.active === tab ? " active" : ""}`}>
                <button type="button" onClick={() => ide.setActive(tab)} title={tab}>
                  {tab.split("/").pop()}
                  {ide.dirty.has(tab) && <span className="dot" />}
                </button>
                <button type="button" className="tab-close" onClick={() => ide.closeTab(tab)}>×</button>
              </div>
            ))}
            {ide.tabs.length === 0 && (
              <div className="tabs-empty">Pressione Ctrl+P para abrir um arquivo</div>
            )}
          </div>

          {trilha.length > 0 && (
            <div className="breadcrumbs">
              {trilha.map((parte, i) => (
                <span key={`${parte}-${i}`}>
                  {i > 0 && <span className="crumb-sep">›</span>}
                  <span className={i === trilha.length - 1 ? "crumb current" : "crumb"}>{parte}</span>
                </span>
              ))}
            </div>
          )}

          <div className="editor-area">
            <Editor
              project={ide.project}
              path={ide.active}
              onDirtyChange={(d) => ide.active && ide.markDirty(ide.active, d)}
              onNavigate={(destino, linha, coluna) =>
                ide.openFile(destino, { line: linha, column: coluna })
              }
              reveal={ide.reveal?.path === ide.active ? ide.reveal : null}
              onRevealed={ide.clearReveal}
              onCursorPositionChange={setCursorPos}
            />
          </div>

          {ide.terminalOpen && (
            <>
              <div
                className="resizer-handle resizer-terminal"
                onMouseDown={() => setIsResizingTerminal(true)}
                title="Arrastar para redimensionar altura do terminal"
              />
              <TerminalPanel sessionId={sessionId} />
            </>
          )}
        </main>

        {ide.agentDockOpen && (
          <div
            className="resizer-handle resizer-agent"
            onMouseDown={() => setIsResizingAgent(true)}
            title="Arrastar para redimensionar painel do agente"
          />
        )}

        {ide.agentDockOpen && (
          <aside className="agent-dock" style={{ width: ide.agentDockWidth }}>
            <AgentDock onFileTouched={ide.openFile} onSession={setSessionId} />
          </aside>
        )}

        <nav className="activity-bar-right">
          <button
            type="button"
            className={`activity${ide.agentDockOpen ? " active" : ""}`}
            title={`Agente de IA (Ctrl+Shift+A)`}
            onClick={() => ide.toggleAgentDock()}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" />
              <path d="M12 6a6 6 0 1 0 6 6 6 6 0 0 0-6-6zm0 10a4 4 0 1 1 4-4 4 4 0 0 1-4 4z" />
            </svg>
          </button>
        </nav>

        {overlay === "quick" && <QuickOpen onClose={() => setOverlay(null)} />}
        {overlay === "palette" && (
          <CommandPalette commands={comandos} onClose={() => setOverlay(null)} />
        )}
      </div>

      <StatusBar lspStatus={{ language: ide.active ? "code" : null, ready: true, error: null }} cursorPosition={cursorPos} />
    </div>
  );
}

export default function IdePage() {
  return (
    <IdeProvider>
      <Shell />
    </IdeProvider>
  );
}
