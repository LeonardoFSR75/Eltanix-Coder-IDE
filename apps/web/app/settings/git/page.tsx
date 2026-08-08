"use client";

import React from "react";
import Link from "next/link";
import { useProject } from "@/components/providers/ProjectContext";
import { GitUserConfigCard } from "@/components/git/GitUserConfigCard";
import { GitHubAccountCard } from "@/components/git/GitHubAccountCard";
import { GitProjectRemoteCard } from "@/components/git/GitProjectRemoteCard";

export default function GitSettingsPage() {
  const { currentProject } = useProject();

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">🐙 Conta Git & GitHub</span>
          <h1>Configuração da Conta Git & GitHub</h1>
          <p>
            Gerencie sua identidade de autor Git local (global ou por projeto), chave de assinatura e token de
            integração com a API do GitHub (PAT).
          </p>
        </div>
        <div className="header-actions">
          <Link
            href={currentProject ? `/ide?project=${encodeURIComponent(currentProject)}` : "/ide"}
            className="btn-primary-sm"
            style={{ textDecoration: "none" }}
          >
            💻 Abrir na IDE
          </Link>
          <Link href="/settings" className="btn-secondary-sm">
            ⚙️ Infraestrutura & Cache
          </Link>
          <Link href="/profile" className="btn-secondary-sm">
            👤 Meu Perfil
          </Link>
        </div>
      </div>

      <div className="flex flex-col gap-6">
        <GitHubAccountCard />

        <GitUserConfigCard currentProject={currentProject} />

        <GitProjectRemoteCard currentProject={currentProject} />
      </div>
    </div>
  );
}
