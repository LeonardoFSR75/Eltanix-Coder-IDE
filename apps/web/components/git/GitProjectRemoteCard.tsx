"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { getGitStatus, type GitStatus } from "@/lib/api/git";

interface GitProjectRemoteCardProps {
  currentProject?: string | null;
}

export function GitProjectRemoteCard({ currentProject }: GitProjectRemoteCardProps) {
  const { addToast } = useToast();

  const [loading, setLoading] = useState(false);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);

  useEffect(() => {
    if (!currentProject) {
      setGitStatus(null);
      return;
    }
    setLoading(true);
    getGitStatus(currentProject)
      .then((data) => setGitStatus(data))
      .catch((err) => {
        addToast(
          err instanceof Error ? err.message : "Falha ao ler status Git do projeto.",
          "error"
        );
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject]);

  if (!currentProject) {
    return (
      <div className="panel-box">
        <div className="panel-header">
          <div className="flex items-center gap-2">
            <span className="text-xl">📁</span>
            <h3>Repositório do Projeto Ativo</h3>
          </div>
        </div>
        <p className="text-xs text-muted mt-2">
          Selecione um projeto na barra superior para visualizar o status do repositório Git local e remotos configurados.
        </p>
      </div>
    );
  }

  return (
    <div className="panel-box">
      <div className="panel-header">
        <div className="flex items-center gap-2">
          <span className="text-xl">📁</span>
          <div>
            <h3 className="m-0 text-base font-semibold">Repositório do Projeto: {currentProject}</h3>
            <p className="text-xs text-muted m-0">
              Controle de versão e estado local dos arquivos do projeto.
            </p>
          </div>
        </div>
        <div>
          {gitStatus ? (
            <span className={`badge-tag ${gitStatus.dirty ? "yellow" : "green"}`}>
              {gitStatus.dirty ? "⚠️ Alterações pendentes" : "✅ Limpo"}
            </span>
          ) : null}
        </div>
      </div>

      {loading ? (
        <p className="text-xs text-muted mt-3">Carregando repositório Git...</p>
      ) : gitStatus ? (
        <div className="mt-4">
          <div className="grid grid-3 gap-3 mb-4">
            <div className="stat-card">
              <div className="stat-label">Branch Ativo</div>
              <div className="stat-value text-base font-mono flex items-center gap-2 mt-1">
                <span>🌿</span> {gitStatus.branch || "—"}
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-label">Commit HEAD</div>
              <div className="stat-value text-base font-mono flex items-center gap-2 mt-1">
                <span>📌</span> {gitStatus.head || "—"}
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-label">Arquivos Alterados</div>
              <div className="stat-value text-base flex items-center gap-2 mt-1">
                <span>📝</span> {gitStatus.files.length} arquivo(s)
              </div>
            </div>
          </div>

          <div className="flex justify-between items-center pt-2">
            <span className="text-xs text-muted">
              Para abrir o painel de diff, realizar commits ou trocar branches:
            </span>
            <Link
              href={`/ide?project=${encodeURIComponent(currentProject)}`}
              className="btn-secondary-sm"
            >
              💻 Abrir no IDE
            </Link>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted mt-2">Nenhum repositório Git encontrado nesta pasta.</p>
      )}
    </div>
  );
}
