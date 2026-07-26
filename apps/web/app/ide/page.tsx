"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Editor } from "@/components/ide/Editor";
import { AgentPanel } from "@/components/ide/AgentPanel";
import { Explorer, GitPanel, SearchPanel } from "@/components/ide/Panels";
import { CommandPalette, QuickOpen, type Command } from "@/components/ide/Overlays";
import { TerminalPanel } from "@/components/ide/Terminal";
import { IdeProvider, useIde, type PanelId } from "@/lib/ide-store";

const PAINEIS: { id: PanelId; icone: string; titulo: string }[] = [
  { id: "explorer", icone: "▤", titulo: "Explorer" },
  { id: "search", icone: "⌕", titulo: "Buscar" },
  { id: "git", icone: "⑂", titulo: "Controle de versão" },
  { id: "agent", icone: "◆", titulo: "Agente" },
];

function Shell() {
  const ide = useIde();
  const [overlay, setOverlay] = useState<"quick" | "palette" | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const comandos = useMemo<Command[]>(
    () => [
      { id: "quick", title: "Ir para arquivo…", shortcut: "Ctrl+P", run: () => setOverlay("quick") },
      { id: "explorer", title: "Mostrar Explorer", run: () => ide.setPanel("explorer") },
      { id: "search", title: "Buscar no projeto", shortcut: "Ctrl+Shift+F", run: () => ide.setPanel("search") },
      { id: "git", title: "Mostrar controle de versão", run: () => ide.setPanel("git") },
      { id: "agent", title: "Mostrar agente", run: () => ide.setPanel("agent") },
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

      if (event.shiftKey && event.key.toLowerCase() === "p") {
        event.preventDefault();
        setOverlay("palette");
      } else if (event.shiftKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        ide.setPanel("search");
      } else if (event.key.toLowerCase() === "p") {
        event.preventDefault();
        setOverlay("quick");
      } else if (event.key === "`") {
        event.preventDefault();
        ide.setTerminalOpen(!ide.terminalOpen);
      } else if (event.key.toLowerCase() === "w" && ide.active) {
        // Ctrl+W fecha a aba do editor, não a janela do browser.
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

  const trilha = ide.active ? ide.active.split("/") : [];

  return (
    <div className="ide">
      <nav className="activity-bar">
        {PAINEIS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`activity${ide.panel === p.id ? " active" : ""}`}
            title={p.titulo}
            onClick={() => ide.setPanel(p.id)}
          >
            {p.icone}
          </button>
        ))}
      </nav>

      <aside className="ide-sidebar">
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

        <div className="panel-title">{PAINEIS.find((p) => p.id === ide.panel)?.titulo}</div>
        {ide.panel === "explorer" && <Explorer />}
        {ide.panel === "search" && <SearchPanel />}
        {ide.panel === "git" && <GitPanel />}
        {ide.panel === "agent" && (
          <div className="panel-body">
            <AgentPanel onFileTouched={ide.openFile} onSession={setSessionId} />
          </div>
        )}
      </aside>

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
            <div className="tabs-empty">Ctrl+P para abrir um arquivo</div>
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
          />
        </div>

        {ide.terminalOpen && <TerminalPanel sessionId={sessionId} />}
      </main>

      {overlay === "quick" && <QuickOpen onClose={() => setOverlay(null)} />}
      {overlay === "palette" && (
        <CommandPalette commands={comandos} onClose={() => setOverlay(null)} />
      )}
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
