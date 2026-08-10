"use client";

import { useEffect, useRef, useState } from "react";
import { useIde, type PanelId } from "@/lib/ide-store";

interface TopMenuBarProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  terminalOpen: boolean;
  onToggleTerminal: () => void;
  agentOpen: boolean;
  onToggleAgent: () => void;
  onOpenQuickOpen?: () => void;
  onOpenCommandPalette?: () => void;
}

type MenuKey = "arquivo" | "editar" | "selecao" | "ver" | "acessar" | "executar" | "terminal" | "ajuda" | null;

export function TopMenuBar({
  sidebarOpen,
  onToggleSidebar,
  terminalOpen,
  onToggleTerminal,
  agentOpen,
  onToggleAgent,
  onOpenQuickOpen,
  onOpenCommandPalette,
}: TopMenuBarProps) {
  const { active, activeGroupId, project, setPanel, splitGroup } = useIde();
  const [activeMenu, setActiveMenu] = useState<MenuKey>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const activeFilename = active ? active.split("/").pop() : null;
  const windowTitle = activeFilename
    ? `SicoobitoCode - Antigravity IDE - ${activeFilename}`
    : `SicoobitoCode - Antigravity IDE ${project ? `(${project})` : ""}`;

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setActiveMenu(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleMenuClick = (key: MenuKey) => {
    setActiveMenu((prev) => (prev === key ? null : key));
  };

  const handleAction = (action: () => void) => {
    setActiveMenu(null);
    action();
  };

  return (
    <header className="ide-top-menubar" ref={menuRef}>
      <div className="top-menubar-brand">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      </div>

      <nav className="top-menubar-menus">
        {/* Arquivo */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "arquivo" ? " active" : ""}`}
            onClick={() => handleMenuClick("arquivo")}
          >
            Arquivo
          </button>
          {activeMenu === "arquivo" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => onOpenQuickOpen?.())}>
                <span>Abrir Arquivo...</span>
                <kbd>Ctrl+P</kbd>
              </button>
              <button type="button" onClick={() => handleAction(() => setPanel("explorer"))}>
                <span>Abrir Pasta do Projeto</span>
                <kbd>Ctrl+O</kbd>
              </button>
              <div className="top-menu-divider" />
              <button type="button" onClick={() => handleAction(() => window.location.reload())}>
                <span>Recarregar Janela</span>
                <kbd>Ctrl+R</kbd>
              </button>
            </div>
          )}
        </div>

        {/* Editar */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "editar" ? " active" : ""}`}
            onClick={() => handleMenuClick("editar")}
          >
            Editar
          </button>
          {activeMenu === "editar" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => setPanel("search"))}>
                <span>Buscar no Projeto</span>
                <kbd>Ctrl+Shift+F</kbd>
              </button>
              <button type="button" onClick={() => handleAction(() => onOpenCommandPalette?.())}>
                <span>Paleta de Comandos</span>
                <kbd>Ctrl+Shift+P</kbd>
              </button>
            </div>
          )}
        </div>

        {/* Seleção */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "selecao" ? " active" : ""}`}
            onClick={() => handleMenuClick("selecao")}
          >
            Seleção
          </button>
          {activeMenu === "selecao" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => onOpenQuickOpen?.())}>
                <span>Selecionar Tudo / Ir para Arquivo</span>
                <kbd>Ctrl+P</kbd>
              </button>
            </div>
          )}
        </div>

        {/* Ver */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "ver" ? " active" : ""}`}
            onClick={() => handleMenuClick("ver")}
          >
            Ver
          </button>
          {activeMenu === "ver" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(onToggleSidebar)}>
                <span>{sidebarOpen ? "Ocultar" : "Exibir"} Barra Lateral</span>
                <kbd>Ctrl+B</kbd>
              </button>
              <button type="button" onClick={() => handleAction(onToggleTerminal)}>
                <span>{terminalOpen ? "Ocultar" : "Exibir"} Terminal</span>
                <kbd>Ctrl+`</kbd>
              </button>
              <button type="button" onClick={() => handleAction(onToggleAgent)}>
                <span>{agentOpen ? "Ocultar" : "Exibir"} Painel do Agente</span>
                <kbd>Ctrl+Shift+A</kbd>
              </button>
              <div className="top-menu-divider" />
              <button type="button" onClick={() => handleAction(() => setPanel("explorer"))}>
                <span>Ir para Explorador</span>
              </button>
              <button type="button" onClick={() => handleAction(() => setPanel("git"))}>
                <span>Ir para Controle de Origem (Git)</span>
              </button>
            </div>
          )}
        </div>

        {/* Acessar */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "acessar" ? " active" : ""}`}
            onClick={() => handleMenuClick("acessar")}
          >
            Acessar
          </button>
          {activeMenu === "acessar" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => onOpenQuickOpen?.())}>
                <span>Ir para Arquivo...</span>
                <kbd>Ctrl+P</kbd>
              </button>
              <button type="button" onClick={() => handleAction(() => onOpenCommandPalette?.())}>
                <span>Ir para Símbolo...</span>
                <kbd>Ctrl+Shift+O</kbd>
              </button>
            </div>
          )}
        </div>

        {/* Executar */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "executar" ? " active" : ""}`}
            onClick={() => handleMenuClick("executar")}
          >
            Executar
          </button>
          {activeMenu === "executar" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => setPanel("debug"))}>
                <span>Iniciar Depuração / Execução</span>
                <kbd>F5</kbd>
              </button>
            </div>
          )}
        </div>

        {/* Terminal */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "terminal" ? " active" : ""}`}
            onClick={() => handleMenuClick("terminal")}
          >
            Terminal
          </button>
          {activeMenu === "terminal" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => { if (!terminalOpen) onToggleTerminal(); })}>
                <span>Novo Terminal Integrado</span>
                <kbd>Ctrl+`</kbd>
              </button>
            </div>
          )}
        </div>

        {/* Ajuda */}
        <div className="top-menu-item-wrap">
          <button
            type="button"
            className={`top-menu-btn${activeMenu === "ajuda" ? " active" : ""}`}
            onClick={() => handleMenuClick("ajuda")}
          >
            Ajuda
          </button>
          {activeMenu === "ajuda" && (
            <div className="top-menu-dropdown">
              <button type="button" onClick={() => handleAction(() => window.open("/docs", "_blank"))}>
                <span>Documentação do SicoobitoCode</span>
              </button>
              <button type="button" onClick={() => handleAction(() => onOpenCommandPalette?.())}>
                <span>Mostrar Todos os Comandos</span>
              </button>
            </div>
          )}
        </div>
      </nav>

      {/* Título Centralizado da Janela */}
      <div className="top-menubar-title" title={windowTitle}>
        {windowTitle}
      </div>

      {/* Botões de Controle de Layout no Canto Direito */}
      <div className="top-menubar-layout-controls">
        <button
          type="button"
          className={`layout-btn${sidebarOpen ? " active" : ""}`}
          onClick={onToggleSidebar}
          title="Alternar Barra Lateral (Ctrl+B)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 3v18" />
          </svg>
        </button>

        <button
          type="button"
          className={`layout-btn${terminalOpen ? " active" : ""}`}
          onClick={onToggleTerminal}
          title="Alternar Painel do Terminal (Ctrl+`)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M3 15h18" />
          </svg>
        </button>

        <button
          type="button"
          className={`layout-btn${agentOpen ? " active" : ""}`}
          onClick={onToggleAgent}
          title="Alternar Dock do Agente (Ctrl+Shift+A)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M15 3v18" />
          </svg>
        </button>

        <button
          type="button"
          className="layout-btn"
          onClick={() => { if (active) splitGroup(activeGroupId, active, "row"); }}
          title="Dividir Editor Lado a Lado"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M12 3v18" />
          </svg>
        </button>
      </div>
    </header>
  );
}
