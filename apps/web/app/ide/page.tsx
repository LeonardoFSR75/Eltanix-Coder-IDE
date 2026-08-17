"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BrowserPanel, ContainersPanel, DebugPanel, Explorer, ExtensionsPanel, GitPanel, PackagesPanel, SearchPanel, TrelloPanel } from "@/components/ide/Panels";

import { StatusBar } from "@/components/ide/StatusBar";
import { TopMenuBar } from "@/components/ide/TopMenuBar";
import { IdeProvider, useIde, type PanelId } from "@/lib/ide-store";
import { ConfirmDialog, PromptDialog, type Command } from "@/components/ide/Overlays";
import { useToast } from "@/components/Toast";

// Cada um destes é um bundle pesado (Monaco, xterm, dock do agente, overlays)
// que só é útil depois que o usuário interage — carregá-los estaticamente
// atrasaria o primeiro paint interativo da rota inteira.
const PaneLayout = dynamic(() => import("@/components/ide/PaneLayout").then((m) => m.PaneLayout), {
  ssr: false,
  loading: () => <EditorSplash project={null} />,
});
const AgentDock = dynamic(() => import("@/components/ide/agent/AgentDock").then((m) => m.AgentDock), {
  ssr: false,
});
const TerminalPanel = dynamic(() => import("@/components/ide/Terminal").then((m) => m.TerminalPanel), {
  ssr: false,
});
const CommandPalette = dynamic(() => import("@/components/ide/Overlays").then((m) => m.CommandPalette), {
  ssr: false,
});
const QuickOpen = dynamic(() => import("@/components/ide/Overlays").then((m) => m.QuickOpen), {
  ssr: false,
});

const PAGINAS_NAVEGAVEIS: { id: string; label: string; href: string }[] = [
  { id: "providers", label: "Provedores & Modelos", href: "/providers" },
  { id: "settings", label: "Cache & Circuit Breakers", href: "/settings" },
  { id: "mcp", label: "Servidores MCP", href: "/mcp" },
  { id: "rag", label: "RAG de Documentos", href: "/rag" },
  { id: "skills", label: "Habilidades (Skills)", href: "/skills" },
  { id: "second-brain", label: "Segundo Cérebro (Notas)", href: "/second-brain" },
  { id: "graphify", label: "Graphify Engine (Grafo de Conhecimento)", href: "/graphify" },
  { id: "requests", label: "Requests recentes", href: "/requests" },
  { id: "audit", label: "Auditoria", href: "/audit" },
  { id: "profile", label: "Perfil & Conexão", href: "/profile" },
];

/** Splash screen exibida quando não há arquivo aberto */
function EditorSplash({ project }: { project: string | null }) {
  return (
    <div className="editor-empty">
      <div className="editor-splash">
        <div className="editor-splash-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="16 18 22 12 16 6" />
            <polyline points="8 6 2 12 8 18" />
          </svg>
        </div>
        <p className="editor-splash-title">
          {project ? project : "SicoobitoCode IDE"}
        </p>
        <p className="editor-splash-sub">
          Abra um arquivo pelo Explorer ou use os atalhos abaixo
        </p>
        <div className="editor-splash-shortcuts">
          {([
            { label: "Ir para arquivo",             keys: ["Ctrl", "P"] },
            { label: "Paleta de comandos",           keys: ["Ctrl", "Shift", "P"] },
            { label: "Buscar no projeto",            keys: ["Ctrl", "Shift", "F"] },
            { label: "Alternar barra lateral",       keys: ["Ctrl", "B"] },
            { label: "Abrir pasta do computador",    keys: ["Ctrl", "O"] },
            { label: "Alternar terminal",            keys: ["Ctrl", "`"] },
          ] as const).map(({ label, keys }) => (
            <div key={label} className="editor-splash-shortcut">
              <span className="editor-splash-shortcut-label">{label}</span>
              <span className="editor-splash-shortcut-keys">
                {keys.map((k, i) => (
                  <kbd key={i} className="editor-kbd">{k}</kbd>
                ))}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Shell() {
  const ide = useIde();
  const router = useRouter();
  const { addToast } = useToast();
  const [overlay, setOverlay] = useState<"quick" | "palette" | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [cursorPos, setCursorPos] = useState<{ line: number; column: number }>({ line: 1, column: 1 });
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [isResizingAgent, setIsResizingAgent] = useState(false);
  const [isResizingTerminal, setIsResizingTerminal] = useState(false);
  const [dialogo, setDialogo] = useState<
    | { tipo: "criar-projeto" }
    | { tipo: "confirmar-git"; nome: string }
    | { tipo: "abrir-pasta" }
    | null
  >(null);
  // ConfirmDialog chama onConfirm() e depois onClose() em sequência no botão
  // "confirmar" (Overlays.tsx) — este ref é o único jeito de onClose (que
  // também roda sozinho no "cancelar"/backdrop) saber se foi um confirm.
  const gitInitRef = useRef(false);

  useEffect(() => {
    ide.setActiveSessionId(sessionId);
  }, [sessionId, ide]);


  // Abrir a aba não basta quando ela já estava aberta: o Editor só refaz o
  // fetch se `path`/`project` mudam ou se `notifyFileChanged` bumpa a versão
  // de sincronia daquele path — sem isto, editar um arquivo que o usuário já
  // tinha aberto (o caso mais comum, já que normalmente se ancora o agente
  // num arquivo focado) deixava a aba mostrando o conteúdo antigo, como se a
  // edição só tivesse acontecido dentro do card do chat.
  const handleAgentFileTouched = useCallback(
    (path: string) => {
      ide.openFile(path);
      ide.notifyFileChanged(path);
    },
    [ide],
  );

  useEffect(() => {
    const handleBrowserOpen = (evt: Event) => {
      const customEvt = evt as CustomEvent<{ url: string; sessionId?: string }>;
      const url = customEvt.detail?.url;
      const sid = customEvt.detail?.sessionId || sessionId;
      if (url) {
        if (sid) ide.setActiveSessionId(sid);
        ide.openFile(`browser:${url}`);
      }
    };
    window.addEventListener("sicoobito:browser:open", handleBrowserOpen);
    return () => window.removeEventListener("sicoobito:browser:open", handleBrowserOpen);
  }, [sessionId, ide]);

  const handleCreateProject = () => {
    setDialogo({ tipo: "criar-projeto" });
  };

  const finalizarCriarProjeto = async (nome: string, gitInit: boolean) => {
    try {
      await ide.createProject(nome, gitInit);
    } catch (err) {
      addToast(`Falha ao criar/vincular projeto: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  };

  const handleOpenAbsolutePath = () => {
    setDialogo({ tipo: "abrir-pasta" });
  };

  const finalizarAbrirPasta = async (caminho: string) => {
    try {
      // Usa o gateway proxy autenticado — nunca chame a API diretamente do browser.
      const res = await fetch("/api/gateway/api/projects/open-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: caminho.trim() }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Erro ao abrir pasta.");
      }
      const data = await res.json();
      await ide.reloadProjects();
      ide.setProject(data.name);
      addToast(`Projeto '${data.name}' aberto! ${data.summary ?? ""}`, "success");
    } catch (err) {
      addToast(`Falha ao abrir pasta: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  };

  const comandos = useMemo<Command[]>(
    () => [
      { id: "open-path", title: "Abrir qualquer pasta do computador…", shortcut: "Ctrl+O", run: () => void handleOpenAbsolutePath() },
      { id: "quick", title: "Ir para arquivo…", shortcut: "Ctrl+P", run: () => setOverlay("quick") },
      { id: "explorer", title: "Mostrar Explorer", run: () => ide.setPanel("explorer") },
      { id: "search", title: "Buscar no projeto", shortcut: "Ctrl+Shift+F", run: () => ide.setPanel("search") },
      { id: "git", title: "Mostrar controle de versão", run: () => ide.setPanel("git") },
      { id: "packages", title: "Mostrar pacotes e dependências (requirements.txt)", run: () => ide.setPanel("packages") },
      { id: "extensions", title: "Mostrar extensões e linguagens (Pyrefly, Python...)", shortcut: "Ctrl+Shift+X", run: () => ide.setPanel("extensions") },
      { id: "containers", title: "Mostrar containers e Docker", shortcut: "Ctrl+Shift+C", run: () => ide.setPanel("containers") },
      { id: "browser", title: "Mostrar navegador", run: () => ide.setPanel("browser") },

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
      ...ide.projects
        .filter((p) => p.name !== ide.project)
        .map((p) => ({
          id: `project-${p.name}`,
          title: `Trocar para projeto: ${p.name}${p.branch ? ` (${p.branch})` : ""}`,
          run: () => ide.setProject(p.name),
        })),
      ...PAGINAS_NAVEGAVEIS.map((pagina) => ({
        id: `nav-${pagina.id}`,
        title: `Ir para: ${pagina.label}`,
        run: () => router.push(pagina.href),
      })),
    ],
    [ide, router],
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
      } else if (event.shiftKey && event.key.toLowerCase() === "x") {
        event.preventDefault();
        ide.setPanel("extensions");
      } else if (event.shiftKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        ide.setPanel("search");
      } else if (event.shiftKey && event.key.toLowerCase() === "a") {
        event.preventDefault();
        ide.toggleAgentDock();
      } else if (event.key.toLowerCase() === "o" && !event.shiftKey) {
        event.preventDefault();
        void handleOpenAbsolutePath();
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
      <TopMenuBar
        sidebarOpen={ide.sidebarOpen}
        onToggleSidebar={() => ide.toggleSidebar()}
        terminalOpen={ide.terminalOpen}
        onToggleTerminal={() => ide.setTerminalOpen(!ide.terminalOpen)}
        agentOpen={ide.agentDockOpen}
        onToggleAgent={() => ide.toggleAgentDock()}
        onOpenQuickOpen={() => setOverlay("quick")}
        onOpenCommandPalette={() => setOverlay("palette")}
      />
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
              else {
                ide.setPanel("git");
                ide.setSidebarOpen(true);
              }
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
            className={`activity${ide.panel === "debug" && ide.sidebarOpen ? " active" : ""}`}
            title="Executar & Debugar (Ctrl+Shift+D)"
            onClick={() => {
              if (ide.panel === "debug" && ide.sidebarOpen) ide.toggleSidebar();
              else {
                ide.setPanel("debug");
                ide.setSidebarOpen(true);
              }
            }}
          >
            {/* Ícone de bug/debug — estilo VSCode */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22c4.97 0 9-4.03 9-9v-1H3v1c0 4.97 4.03 9 9 9z" />
              <path d="M12 12V2" />
              <path d="M8 6l4-4 4 4" />
              <path d="M3 12H1" />
              <path d="M23 12h-2" />
              <path d="M3 8l-1.5-2" />
              <path d="M21 8l1.5-2" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "browser" && ide.sidebarOpen ? " active" : ""}`}
            title="Navegador (verificação visual)"
            onClick={() => {
              if (ide.panel === "browser" && ide.sidebarOpen) ide.toggleSidebar();
              else {
                ide.setPanel("browser");
                ide.setSidebarOpen(true);
              }
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "packages" && ide.sidebarOpen ? " active" : ""}`}
            title="Pacotes & Dependências (requirements.txt)"
            onClick={() => {
              if (ide.panel === "packages" && ide.sidebarOpen) ide.toggleSidebar();
              else {
                ide.setPanel("packages");
                ide.setSidebarOpen(true);
              }
            }}
          >
            {/* Ícone de caixa/pacote */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
              <line x1="12" y1="22.08" x2="12" y2="12" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "extensions" && ide.sidebarOpen ? " active" : ""}`}
            title="Extensões & Linguagens (Pyrefly, Python...)"
            onClick={() => {
              if (ide.panel === "extensions" && ide.sidebarOpen) ide.toggleSidebar();
              else {
                ide.setPanel("extensions");
                ide.setSidebarOpen(true);
              }
            }}
          >
            {/* Ícone de extensão de 4 blocos estilo VSCode (Blocks / Grid) */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "containers" && ide.sidebarOpen ? " active" : ""}`}
            title="Containers & Docker (Status & Stack)"
            onClick={() => {
              if (ide.panel === "containers" && ide.sidebarOpen) ide.toggleSidebar();
              else {
                ide.setPanel("containers");
                ide.setSidebarOpen(true);
              }
            }}
          >
            {/* Ícone vetorial de Docker / Containers estilo VSCode */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="10" width="3" height="3" rx="0.5" />
              <rect x="7" y="10" width="3" height="3" rx="0.5" />
              <rect x="11" y="10" width="3" height="3" rx="0.5" />
              <rect x="7" y="6" width="3" height="3" rx="0.5" />
              <rect x="11" y="6" width="3" height="3" rx="0.5" />
              <rect x="15" y="10" width="3" height="3" rx="0.5" />
              <path d="M2 14c0 3.5 3 6 7 6h6c3.5 0 6.5-2 7-4.5.2-.8-.2-1.5-1-1.5h-1c-.5 0-1-.2-1.3-.6l-1.2-1.4" />
            </svg>
          </button>

          <button
            type="button"
            className={`activity${ide.panel === "trello" && ide.sidebarOpen ? " active" : ""}`}
            title="Quadro Trello / Kanban do Projeto"
            onClick={() => {
              if (ide.panel === "trello" && ide.sidebarOpen) ide.toggleSidebar();
              else {
                ide.setPanel("trello");
                ide.setSidebarOpen(true);
              }
            }}
          >
            {/* Ícone vetorial de Kanban / Trello */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <rect x="7" y="7" width="3" height="10" rx="1" />
              <rect x="14" y="7" width="3" height="6" rx="1" />
            </svg>
          </button>



          <button
            type="button"
            className="activity"
            title="Graphify Engine (Grafo de Conhecimento)"
            onClick={() => router.push("/graphify")}
          >
            {/* Ícone de grafo/rede */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="18" cy="5" r="3" />
              <circle cx="6" cy="12" r="3" />
              <circle cx="18" cy="19" r="3" />
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
              <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
            </svg>
          </button>

          <button
            type="button"
            className="activity"
            title="Segundo Cérebro (Notas & Base)"
            onClick={() => router.push("/second-brain")}
          >
            {/* Ícone de cérebro/base de conhecimento */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z" />
              <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z" />
            </svg>
          </button>

          <button
            type="button"
            className="activity sidebar-toggle-btn"
            style={{ marginTop: "auto" }}
            title={`Alternar barra lateral (Ctrl+B)`}
            onClick={() => ide.toggleSidebar()}
          >
            {/* Chevron animado */}
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ transform: ide.sidebarOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.25s ease" }}
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
        </nav>

        {ide.sidebarOpen && (
          <aside className="ide-sidebar" style={{ width: ide.sidebarWidth }}>
            <div className="project-picker">
              <div className="project-picker-select-wrapper">
                <span className="project-picker-icon">📁</span>
                <select
                  value={ide.project ?? ""}
                  onChange={(e) => ide.setProject(e.target.value)}
                  title="Projeto/repositório ativo no workspace"
                  className="project-picker-select"
                >
                  {ide.projects.length === 0 && <option value="">Nenhum projeto aberto</option>}
                  {ide.projects.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}{p.branch ? ` (${p.branch})` : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div className="project-picker-actions">
                <button
                  type="button"
                  onClick={handleOpenAbsolutePath}
                  className="project-action-btn primary"
                  title="Abrir qualquer pasta absoluta do seu computador (Windows/Linux/macOS)"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    <line x1="12" y1="11" x2="12" y2="17" />
                    <line x1="9" y1="14" x2="15" y2="14" />
                  </svg>
                  <span>Abrir</span>
                </button>
                <button
                  type="button"
                  onClick={handleCreateProject}
                  className="project-action-btn secondary"
                  title="Criar uma nova pasta de projeto no diretório PROJECTS_ROOT"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                  <span>Novo</span>
                </button>
              </div>
            </div>
            {ide.projectsError && <div className="panel-error">{ide.projectsError}</div>}

            {ide.panel === "explorer" && <Explorer />}
            {ide.panel === "search" && <SearchPanel />}
            {ide.panel === "git" && <GitPanel />}
            {ide.panel === "debug" && <DebugPanel />}
            {ide.panel === "browser" && <BrowserPanel />}
            {ide.panel === "packages" && <PackagesPanel />}
            {ide.panel === "trello" && <TrelloPanel />}
            {ide.panel === "extensions" && <ExtensionsPanel />}
            {ide.panel === "containers" && <ContainersPanel />}
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
          <PaneLayout onCursorPositionChange={setCursorPos} />

          {ide.terminalOpen && (
            <>
              <div
                className="resizer-handle resizer-terminal"
                onMouseDown={() => setIsResizingTerminal(true)}
                title="Arrastar para redimensionar altura do terminal"
              />
              <TerminalPanel
                sessionId={sessionId}
                project={ide.project}
                onSessionCreated={setSessionId}
                onClose={() => ide.setTerminalOpen(false)}
              />
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
            <AgentDock onFileTouched={handleAgentFileTouched} onSession={setSessionId} />
          </aside>
        )}

        <nav className="activity-bar-right">
          <button
            type="button"
            className={`activity${ide.agentDockOpen ? " active" : ""}`}
            title={`Agente de IA (Ctrl+Shift+A)`}
            onClick={() => ide.toggleAgentDock()}
            style={{ position: "relative" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" />
              <path d="M12 6a6 6 0 1 0 6 6 6 6 0 0 0-6-6zm0 10a4 4 0 1 1 4-4 4 4 0 0 1-4 4z" />
            </svg>
          </button>
        </nav>

        {overlay === "quick" && <QuickOpen onClose={() => setOverlay(null)} />}
        {overlay === "palette" && (
          <CommandPalette commands={comandos} onClose={() => setOverlay(null)} />
        )}

        {dialogo?.tipo === "criar-projeto" && (
          <PromptDialog
            title="Nome da pasta do projeto (será criada ou vinculada dentro do PROJECTS_ROOT):"
            confirmLabel="próximo"
            onConfirm={(nome) => {
              gitInitRef.current = false;
              setDialogo({ tipo: "confirmar-git", nome });
            }}
            onClose={() => setDialogo((d) => (d?.tipo === "criar-projeto" ? null : d))}
          />
        )}
        {dialogo?.tipo === "confirmar-git" && (
          <ConfirmDialog
            message={
              <>
                Deseja inicializar um repositório Git nesta pasta?
                <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 6 }}>
                  &quot;confirmar&quot; cria o projeto com Git; &quot;cancelar&quot; cria sem Git.
                </div>
              </>
            }
            onConfirm={() => { gitInitRef.current = true; }}
            onClose={() => {
              const nome = dialogo.nome;
              const gitInit = gitInitRef.current;
              gitInitRef.current = false;
              setDialogo(null);
              void finalizarCriarProjeto(nome, gitInit);
            }}
          />
        )}
        {dialogo?.tipo === "abrir-pasta" && (
          <PromptDialog
            title="Digite ou cole o caminho absoluto de QUALQUER pasta do computador (ex: C:\Projetos\ERP ou /home/user/app):"
            confirmLabel="abrir"
            onConfirm={(caminho) => void finalizarAbrirPasta(caminho)}
            onClose={() => setDialogo(null)}
          />
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
