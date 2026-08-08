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
  const PROJECT_AWARE_PATHS = new Set(["/rag", "/graphify", "/second-brain", "/requests"]);
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

  // ✅ FIX: navGroups movido para fora do componente (sem closures dinâmicos)
  // O item de logout é identificado por isAction: true e tratado separadamente no render
  const navGroups: NavGroup[] = [
    {
      label: "Desenvolvimento",
      icon: "💻",
      items: [
        { href: "/projects", label: "Central de Projetos", icon: "🚀", description: "Projetos, Custos 360°, Git & Auditoria" },
        { href: "/ide", label: "IDE Agêntica", icon: "💻", description: "Editor Monaco + Terminal + Pyright" },
        { href: "/providers", label: "Provedores LLM", icon: "🌐", description: "Ollama, OpenAI & Gateway" },
        { href: "/requests", label: "Requests & Custo", icon: "📊", description: "FinOps, Tokens & Cache Exato" },
      ],
    },
    {
      label: "Inteligência & RAG",
      icon: "🧠",
      items: [
        { href: "/rag", label: "RAG & ChromaDB", icon: "📚", description: "Busca Vetorial & PDFs no BD" },
        { href: "/graphify", label: "Graphify Engine", icon: "🕸️", description: "Knowledge Graph & GraphRAG" },
        { href: "/second-brain", label: "Segundo Cérebro", icon: "📓", description: "Grafo Obsidian & Wikilinks" },
      ],
    },
    {
      label: "Agentes & MCP",
      icon: "⚡",
      items: [
        { href: "/skills", label: "Skills do Agente", icon: "⚡", description: "Sandbox & Prompts de Ferramentas" },
        { href: "/mcp", label: "Servidores MCP", icon: "🔌", description: "JSON-RPC 2.0 (STDIO / SSE)" },
      ],
    },
    {
      label: "Governança & Conta",
      icon: "🛡️",
      items: [
        { href: "/profile", label: "Meu Perfil & Chaves API", icon: "👤", description: "Gestão de Usuário & Credenciais" },
        { href: "/login", label: "Autenticação", icon: "🔑", description: "Login e sessão atual" },
        { href: "/audit", label: "Logs de Auditoria", icon: "🛡️", description: "Trilha de Segurança & Guardrails" },
        { href: "/settings", label: "Configurações", icon: "⚙️", description: "ChromaDB Host & Banco de Dados" },
        { href: "#logout", label: "Sair da Conta (Logout)", icon: "🚪", description: "Encerrar sessão atual", isAction: true },
      ],
    },
  ];

  const toggleDropdown = (label: string) => {
    setActiveDropdown((prev) => (prev === label ? null : label));
  };

  return (
    <header className={`topbar ${isIde ? "topbar-ide" : ""}`}>
      <div className="brand-wrap">
        <Link href="/" className="brand-link">
          <div className="brand-logo">S</div>
          <span className="brand-name">
            Sicoobito<span className="brand-highlight">Code</span>
          </span>
        </Link>
      </div>

      <nav className="nav tree-nav" ref={navRef}>
        {/* Link Direto Home */}
        <Link
          href="/"
          className={`nav-link ${pathname === "/" ? "active" : ""}`}
          onClick={() => setActiveDropdown(null)}
        >
          <span className="nav-icon">🏠</span>
          Home
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
          <div className="user-profile-badge-wrapper">
            <Link href="/profile" className="user-profile-badge" title="Configurações">
              <span className="user-avatar">🔑</span>
              <div className="user-info">
                <span className="user-name">{user.displayName || user.username}</span>
                <span className="user-role">Conectado</span>
              </div>
            </Link>
            <button
              type="button"
              onClick={handleUserLogout}
              className="logout-nav-btn"
              title="Sair da Conta (Logout)"
            >
              🚪 Sair
            </button>
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
