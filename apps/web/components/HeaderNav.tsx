"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "@/lib/theme";
import { useAuth } from "@/components/providers/AuthContext";
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
  const { addToast } = useToast();
  const isIde = pathname.startsWith("/ide");

  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const navRef = useRef<HTMLDivElement | null>(null);

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
  const handleUserLogout = useCallback(() => {
    logout();
    addToast("Você saiu da sua conta.", "info");
    router.push("/login");
  }, [logout, addToast, router]);

  // ✅ FIX: navGroups movido para fora do componente (sem closures dinâmicos)
  // O item de logout é identificado por isAction: true e tratado separadamente no render
  const navGroups: NavGroup[] = [
    {
      label: "Desenvolvimento",
      icon: "💻",
      items: [
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
        { href: "/second-brain", label: "Segundo Cérebro", icon: "📓", description: "Grafo Obsidian & Wikilinks" },
        { href: "/neural-network", label: "Rede Neural 2D", icon: "🧠", description: "Simulador de Arquiteturas" },
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
        { href: "/login", label: "Autenticação / Passkey", icon: "🔑", description: "Entrar & Alternar Contas" },
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
        <span className="brand-badge">Local-First</span>
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
                          href={item.href}
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
        <div className="db-badge-group">
          <span className="mini-badge db-online" title="PostgreSQL 17 + pgvector (Porta 5403)">
            <span className="pulse-dot-green" /> Postgres
          </span>
          <span className="mini-badge redis-online" title="Redis Cache L1, Redlock & Circuit Breaker (Porta 5404)">
            <span className="pulse-dot-red" /> Redis L1
          </span>
          <span className="mini-badge chroma-online" title="ChromaDB Vector Gateway Online">
            <span className="pulse-dot-blue" /> ChromaDB
          </span>
          <span className="mini-badge minio-online" title="MinIO S3 Object Storage Online (Porta 5407/5408)">
            <span className="pulse-dot-yellow" /> MinIO S3
          </span>
        </div>

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
            <Link href="/profile" className="user-profile-badge" title="Ver Perfil">
              <span className="user-avatar">{user.avatar}</span>
              <div className="user-info">
                <span className="user-name">{user.name}</span>
                <span className="user-role">{user.role}</span>
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
