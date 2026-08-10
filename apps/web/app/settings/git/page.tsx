"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useProject } from "@/components/providers/ProjectContext";
import { GitSetupGuideCard } from "@/components/git/GitSetupGuideCard";
import { GitUserConfigCard } from "@/components/git/GitUserConfigCard";
import { GitHubAccountCard } from "@/components/git/GitHubAccountCard";
import { GitProjectRemoteCard } from "@/components/git/GitProjectRemoteCard";

function GitSettingsContent() {
  const { currentProject, projects, setCurrentProject } = useProject();
  const searchParams = useSearchParams();
  const urlProject = searchParams.get("project");

  const activeProject = urlProject || currentProject;

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
            href={activeProject ? `/ide?project=${encodeURIComponent(activeProject)}` : "/ide"}
            className="btn-primary-sm"
            style={{ textDecoration: "none" }}
          >
            💻 Abrir na IDE
          </Link>

          {activeProject && (
            <Link
              href={`/projects/${encodeURIComponent(activeProject)}`}
              className="btn-secondary-sm"
            >
              📊 Hub 360° do Projeto
            </Link>
          )}

          <Link href="/settings" className="btn-secondary-sm">
            ⚙️ Configurações Gerais
          </Link>
        </div>
      </div>

      {/* Indicador e Seletor de Escopo do Projeto */}
      <div
        className="p-4 rounded-lg mb-6 flex flex-wrap items-center justify-between gap-4"
        style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl">📁</span>
          <div>
            <div className="text-xs text-muted font-semibold">ESCOPO ATUAL DE PROJETO</div>
            <div className="text-sm font-bold flex items-center gap-2">
              {activeProject ? (
                <>
                  <span>{activeProject}</span>
                  <span className="badge-tag green">Projeto Ativo</span>
                </>
              ) : (
                <span className="text-muted font-normal">Nenhum projeto selecionado (Modo Global)</span>
              )}
            </div>
          </div>
        </div>

        {projects && projects.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted font-medium">Trocar Projeto:</span>
            <select
              value={activeProject || ""}
              onChange={(e) => {
                if (e.target.value) {
                  setCurrentProject(e.target.value);
                }
              }}
              className="input-select text-xs font-mono py-1.5 px-3"
              style={{
                borderRadius: "var(--radius)",
                backgroundColor: "var(--surface-2)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
            >
              <option value="">-- Seleção Global --</option>
              {projects.map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.name} ({p.slug})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-6">
        {/* Seção 1: Guia Explicativo */}
        <GitSetupGuideCard />

        {/* Seção 2: Conexão Global do GitHub */}
        <section>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <span>🌐</span> Nível Global (Máquina & Plataforma)
          </div>
          <GitHubAccountCard />
        </section>

        {/* Seção 3: Identidade do Autor Git (Global ou Escopado) */}
        <section>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <span>👤</span> Identidade do Autor (`user.name` & `user.email`)
          </div>
          <GitUserConfigCard currentProject={activeProject} />
        </section>

        {/* Seção 4: Status do Repositório do Projeto */}
        <section>
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <span>📁</span> Status & Remotos do Projeto (`git remote`)
          </div>
          <GitProjectRemoteCard currentProject={activeProject} />
        </section>
      </div>
    </div>
  );
}

export default function GitSettingsPage() {
  return (
    <Suspense fallback={<div className="shell p-6 text-muted text-xs">Carregando configurações Git...</div>}>
      <GitSettingsContent />
    </Suspense>
  );
}
