"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "@/lib/theme";
import { useAuth } from "@/components/providers/AuthContext";
import { useProject } from "@/components/providers/ProjectContext";
import { useToast } from "@/components/Toast";

interface NavItem {
  href: string;
  label: string;
  icon: string;
  description: string;
  isAction?: boolean;
}

interface NavGroup {
  label: string;
  icon: string;
  items: NavItem[];
}

export function HeaderNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const { currentProject, projects, setCurrentProject } = useProject();
  const { addToast } = useToast();
  const isIde = pathname.startsWith("/ide");

  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const navRef = useRef<HTMLDivElement | null>(null);

  // Grupos cujo destino sabe filtrar por projeto (ver `?project=` em cada
  // página) — trocar de projeto aqui já leva a navegação seguinte filtrada,
  // fechando o ciclo "entro pelo Hub, tudo que abro dali já sabe do projeto".
  const PROJECT_AWARE_PATHS = new Set(["/ide", "/browser", "/trello", "/rag", "/graphify", "/second-brain", "/requests"]);
  const projectHref = (href: string) =>
    currentProject && PROJECT_AWARE_PATHS.has(href)
      ? `${href}?project=${encodeURIComponent(currentProject)}`
      : href;

  // Fechar dropdowns ao clicar fora
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setActiveDropdown(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // ✅ FIX: useCallback para evitar re-criação da função em cada render
  const handleUserLogout = useCallback(async () => {
    await logout();
    addToast("Sessão encerrada.", "info");
    router.push("/login");
  }, [logout, addToast, router]);

  const navGroups: NavGroup[] = [
    {
      label: "Projeto",
      icon: "📁",
      items: [
        { href: "/ide", label: "IDE Agêntica", icon: "💻", description: "Editor Monaco + Terminal + Agente" },
        { href: "/browser", label: "Navegador Interno", icon: "🌐", description: "Browser Live + Headless com Tela Cheia e DevTools" },
        { href: "/trello", label: "Quadro Trello (Kanban)", icon: "📋", description: "Quadro de tarefas, sprints e cartões do projeto" },
        { href: "/graphify", label: "Graphify Engine", icon: "🕸️", description: "Knowledge Graph & GraphRAG do projeto" },
        { href: "/second-brain", label: "Segundo Cérebro", icon: "📓", description: "Notas Obsidian & Wikilinks do projeto" },
        { href: "/rag", label: "RAG & Documentos", icon: "📚", description: "Busca vetorial & PDFs do projeto" },
        { href: "/requests", label: "FinOps & Custos", icon: "📊", description: "Consumo de tokens e custos do projeto" },
      ],
    },
    {
      label: "Plataforma",
      icon: "🌐",
      items: [
        { href: "/analytics", label: "Analytics ML & Diagnósticos", icon: "🧠", description: "Telemetria ML, falhas preditivas e propostas autônomas" },
        { href: "/skills", label: "Skills do Agente", icon: "⚡", description: "Prompts & Sandboxes de ferramentas" },
        { href: "/mcp", label: "Servidores MCP", icon: "🔌", description: "Integrações Protocolo MCP (STDIO / SSE)" },
        { href: "/providers", label: "Provedores LLM", icon: "🌐", description: "Ollama, OpenAI & Gateway da API" },
        { href: "/settings/git", label: "Conta Git & GitHub", icon: "🐙", description: "Identidade de autor & token do GitHub (PAT)" },
        { href: "/audit", label: "Trilha de Auditoria", icon: "🛡️", description: "Logs globais de segurança & guardrails" },
        { href: "/settings", label: "Configurações", icon: "⚙️", description: "Parâmetros do sistema & banco de dados" },
      ],
    },
  ];

  const toggleDropdown = (label: string) => {
    setActiveDropdown((prev) => (prev === label ? null : label));
  };

  return (
    <header className={`topbar ${isIde ? "topbar-ide" : ""}`}>
      <div className="brand-wrap">
        <Link href="/projects" className="brand-link">
          <div className="brand-logo">S</div>
          <span className="brand-name">
            Sicoobito<span className="brand-highlight">Code</span>
          </span>
        </Link>
      </div>

      {user && pathname !== "/login" && (
        <nav className="nav tree-nav" ref={navRef}>
        {/* Link Direto Central de Projetos (Home) */}
        <Link
          href="/projects"
          className={`nav-link ${pathname === "/" || pathname === "/projects" ? "active" : ""}`}
          onClick={() => setActiveDropdown(null)}
        >
          <span className="nav-icon">🚀</span>
          Central de Projetos
        </Link>

        {/* Dropdowns Agrupados por Categoria */}
        {navGroups.map((group) => {
          const isGroupActive = group.items.some(
            (item) => !item.isAction && pathname === item.href
          );
          const isOpen = activeDropdown === group.label;

          return (
            <div key={group.label} className="nav-dropdown-wrapper">
              <button
                type="button"
                className={`nav-dropdown-btn ${isGroupActive ? "active" : ""} ${isOpen ? "open" : ""}`}
                onClick={() => toggleDropdown(group.label)}
              >
                <span className="nav-icon">{group.icon}</span>
                {group.label}
                <span className="chevron-icon">{isOpen ? "▲" : "▼"}</span>
              </button>

              {isOpen && (
                <div className="nav-dropdown-menu animate-fade-in">
                  <div className="dropdown-header">
                    <span className="dropdown-category-title">{group.label}</span>
                  </div>
                  <div className="dropdown-items-list">
                    {group.items.map((item) => {
                      if (item.isAction) {
                        return (
                          <button
                            key={item.href}
                            type="button"
                            className="dropdown-item dropdown-item-danger"
                            onClick={() => {
                              setActiveDropdown(null);
                              handleUserLogout();
                            }}
                          >
                            <span className="item-icon">{item.icon}</span>
                            <div className="item-text">
                              <span className="item-label">{item.label}</span>
                              <span className="item-desc">{item.description}</span>
                            </div>
                          </button>
                        );
                      }
                      const isItemActive = pathname === item.href;
                      return (
                        <Link
                          key={item.href}
                          href={projectHref(item.href)}
                          className={`dropdown-item ${isItemActive ? "active" : ""}`}
                          onClick={() => setActiveDropdown(null)}
                        >
                          <span className="item-icon">{item.icon}</span>
                          <div className="item-text">
                            <span className="item-label">{item.label}</span>
                            <span className="item-desc">{item.description}</span>
                          </div>
                        </Link>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </nav>
      )}

      <div className="topbar-actions">
        {user && projects.length > 0 && (
          <select
            className="project-picker-select"
            value={currentProject ?? ""}
            onChange={(e) => setCurrentProject(e.target.value || null)}
            title="Projeto atual"
          >
            <option value="">Sem projeto</option>
            {projects.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
        )}

        <button
          type="button"
          className="theme-btn"
          onClick={toggleTheme}
          title={`Alternar para modo ${theme === "dark" ? "claro" : "escuro"}`}
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>

        {user ? (
          <div className="user-profile-badge-wrapper" style={{ position: "relative" }}>
            <button
              type="button"
              className={`user-profile-badge ${activeDropdown === "user_menu" ? "active" : ""}`}
              onClick={() => toggleDropdown("user_menu")}
              title="Menu do Usuário"
              style={{ background: "none", border: "1px solid var(--border)", cursor: "pointer", textAlign: "left" }}
            >
              <span className="user-avatar">🔑</span>
              <div className="user-info">
                <span className="user-name">{user.displayName || user.username}</span>
                <span className="user-role">
                  Conectado <span style={{ fontSize: "9px", marginLeft: "2px" }}>{activeDropdown === "user_menu" ? "▲" : "▼"}</span>
                </span>
              </div>
            </button>

            {activeDropdown === "user_menu" && (
              <div
                className="nav-dropdown-menu animate-fade-in"
                style={{ right: 0, left: "auto", minWidth: "240px", top: "calc(100% + 6px)" }}
              >
                <div className="dropdown-header">
                  <span className="dropdown-category-title">USUÁRIO & SESSÃO</span>
                </div>
                <div className="dropdown-items-list">
                  <Link
                    href="/profile"
                    className={`dropdown-item ${pathname === "/profile" ? "active" : ""}`}
                    onClick={() => setActiveDropdown(null)}
                  >
                    <span className="item-icon">👤</span>
                    <div className="item-text">
                      <span className="item-label">Meu Perfil & Senha</span>
                      <span className="item-desc">Gestão de conta & alteração de senha</span>
                    </div>
                  </Link>

                  <Link
                    href="/login"
                    className={`dropdown-item ${pathname === "/login" ? "active" : ""}`}
                    onClick={() => setActiveDropdown(null)}
                  >
                    <span className="item-icon">🔑</span>
                    <div className="item-text">
                      <span className="item-label">Status da Sessão</span>
                      <span className="item-desc">Sessão ativa e credenciais</span>
                    </div>
                  </Link>

                  <button
                    type="button"
                    className="dropdown-item dropdown-item-danger"
                    onClick={() => {
                      setActiveDropdown(null);
                      handleUserLogout();
                    }}
                  >
                    <span className="item-icon">🚪</span>
                    <div className="item-text">
                      <span className="item-label">Sair da Conta (Logout)</span>
                      <span className="item-desc">Encerrar sessão ativa</span>
                    </div>
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <Link href="/login" className="login-nav-btn">
            🔑 Entrar
          </Link>
        )}
      </div>
    </header>
  );
}
