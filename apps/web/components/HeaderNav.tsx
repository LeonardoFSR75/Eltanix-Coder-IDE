"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "@/lib/theme";

export function HeaderNav() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const isIde = pathname.startsWith("/ide");

  const links = [
    { href: "/ide", label: "IDE", icon: "⚡" },
    { href: "/", label: "Custo & Uso", icon: "📊" },
    { href: "/providers", label: "Provedores", icon: "🌐" },
    { href: "/requests", label: "Requests", icon: "📋" },
  ];

  return (
    <header className={`topbar ${isIde ? "topbar-ide" : ""}`}>
      <div className="brand-wrap">
        <div className="brand-logo">S</div>
        <span className="brand-name">
          Sicoobito<span className="brand-highlight">Code</span>
        </span>
        <span className="brand-badge">Local-First</span>
      </div>

      <nav className="nav">
        {links.map((link) => {
          const isActive = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`nav-link ${isActive ? "active" : ""}`}
            >
              <span className="nav-icon">{link.icon}</span>
              {link.label}
            </Link>
          );
        })}
      </nav>

      <div className="topbar-actions">
        <button
          type="button"
          className="theme-btn"
          onClick={toggleTheme}
          title={`Alternar para modo ${theme === "dark" ? "claro" : "escuro"}`}
        >
          {theme === "dark" ? "☀️ Claro" : "🌙 Escuro"}
        </button>

        <div className="topbar-status">
          <span className="pulse-dot" />
          <span className="status-text">Gateway Online</span>
        </div>
      </div>
    </header>
  );
}
