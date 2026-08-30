"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import {
  browseFilesystem,
  createProject,
  FsBrowseResult,
  inspectPath,
  openAbsolutePath,
  ProjectRecord,
  ProjectSignature,
} from "@/lib/api/projects";

export interface LinkProjectModalProps {
  initialTab?: "link" | "create" | "clone";
  onClose: () => void;
  onProjectOpened: (slug: string, name: string) => void;
}

export function LinkProjectModal({
  initialTab = "link",
  onClose,
  onProjectOpened,
}: LinkProjectModalProps) {
  const [tab, setTab] = useState<"link" | "create" | "clone">(initialTab);
  const { addToast } = useToast();

  // ── Tab 1: Vincular Pasta Existente (Filesystem Explorer & Native Picker)
  const [selectedPath, setSelectedPath] = useState("");
  const [fsData, setFsData] = useState<FsBrowseResult | null>(null);
  const [fsLoading, setFsLoading] = useState(false);
  const [signature, setSignature] = useState<ProjectSignature | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [linking, setLinking] = useState(false);

  // ── Tab 2: Criar Novo Projeto
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newLanguage, setNewLanguage] = useState<string>("python");
  const [newInitGit, setNewInitGit] = useState(true);
  const [newCreateGithub, setNewCreateGithub] = useState(false);
  const [newBudgetLimit, setNewBudgetLimit] = useState("");
  const [creating, setCreating] = useState(false);

  // ── Tab 3: Clonar do Git
  const [cloneUrl, setCloneUrl] = useState("");
  const [cloneName, setCloneName] = useState("");
  const [cloning, setCloning] = useState(false);

  // Carrega o sistema de arquivos ao abrir a aba "link"
  const carregarFs = useCallback(
    async (path?: string) => {
      setFsLoading(true);
      try {
        const data = await browseFilesystem(path);
        setFsData(data);
        if (data.current_path) {
          setSelectedPath(data.current_path);
          void inspecionar(data.current_path);
        }
      } catch (err) {
        addToast(
          `Falha ao explorar pastas: ${err instanceof Error ? err.message : String(err)}`,
          "error",
        );
      } finally {
        setFsLoading(false);
      }
    },
    [addToast],
  );

  const inspecionar = useCallback(async (path: string) => {
    if (!path || !path.trim()) {
      setSignature(null);
      return;
    }
    setInspecting(true);
    try {
      const sig = await inspectPath(path.trim());
      setSignature(sig);
    } catch {
      setSignature(null);
    } finally {
      setInspecting(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "link" && !fsData) {
      void carregarFs();
    }
  }, [tab, fsData, carregarFs]);

  // Não há mais um botão de "seletor nativo" (File System Access API) aqui:
  // `window.showDirectoryPicker()` entrega só o NOME da pasta escolhida,
  // nunca o caminho absoluto — é assim de propósito, por sandboxing do
  // browser. Usar `dirHandle.name` como se fosse um caminho vinculava a
  // pasta errada sempre que outra pasta com o mesmo nome já existisse sob
  // `PROJECTS_ROOT` (ex.: escolher "D:\work\Sorteador" na janela nativa e a
  // IDE silenciosamente abrir `PROJECTS_ROOT/Sorteador` no lugar). O
  // navegador de pastas abaixo (`browseFilesystem`) é a via correta: devolve
  // caminhos absolutos de verdade, resolvidos no backend.

  const handleLinkFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedPath.trim()) {
      addToast("Informe ou selecione uma pasta para vincular.", "warning");
      return;
    }

    setLinking(true);
    try {
      const result = await openAbsolutePath(selectedPath.trim());
      addToast(`Projeto '${result.name}' vinculado com sucesso!`, "success");
      onProjectOpened(result.slug, result.name);
      onClose();
    } catch (err) {
      addToast(
        `Erro ao vincular pasta: ${err instanceof Error ? err.message : String(err)}`,
        "error",
      );
    } finally {
      setLinking(false);
    }
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) {
      addToast("Informe o nome do projeto.", "warning");
      return;
    }

    setCreating(true);
    try {
      const created: ProjectRecord = await createProject({
        name: newName.trim(),
        description: newDesc.trim() || undefined,
        language: newLanguage,
        init_git: newInitGit,
        create_github_repo: newCreateGithub,
        budget_limit_usd: newBudgetLimit ? parseFloat(newBudgetLimit) : undefined,
      });
      addToast(`Projeto '${created.name}' criado com sucesso!`, "success");
      onProjectOpened(created.slug, created.name);
      onClose();
    } catch (err) {
      addToast(
        `Erro ao criar projeto: ${err instanceof Error ? err.message : String(err)}`,
        "error",
      );
    } finally {
      setCreating(false);
    }
  };

  const handleCloneProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cloneUrl.trim()) {
      addToast("Informe a URL do repositório Git.", "warning");
      return;
    }

    const derivedName =
      cloneName.trim() ||
      cloneUrl
        .split("/")
        .pop()
        ?.replace(/\.git$/i, "") ||
      "projeto-clonado";

    setCloning(true);
    try {
      const created = await createProject({
        name: derivedName,
        git_url: cloneUrl.trim(),
        init_git: true,
      });
      addToast(`Projeto '${created.name}' vinculado ao repositório Git!`, "success");
      onProjectOpened(created.slug, created.name);
      onClose();
    } catch (err) {
      addToast(
        `Erro ao clonar projeto: ${err instanceof Error ? err.message : String(err)}`,
        "error",
      );
    } finally {
      setCloning(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.78)",
        backdropFilter: "blur(6px)",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 1100,
        padding: "1rem",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          backgroundColor: "var(--surface, #181825)",
          borderRadius: "14px",
          border: "1px solid var(--border, #313244)",
          width: "100%",
          maxWidth: "760px",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 25px 60px -15px rgba(0, 0, 0, 0.7)",
          overflow: "hidden",
          animation: "modalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
        }}
      >
        {/* Header com Abas */}
        <div
          style={{
            padding: "1.25rem 1.5rem 0 1.5rem",
            borderBottom: "1px solid var(--border, #313244)",
            backgroundColor: "var(--surface-2, #1e1e2e)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <span style={{ fontSize: "1.5rem" }}>🚀</span>
              <div>
                <h2
                  style={{
                    margin: 0,
                    fontSize: "1.25rem",
                    fontWeight: 700,
                    color: "var(--text, #cdd6f4)",
                  }}
                >
                  Central de Vinculação de Projetos
                </h2>
                <p
                  style={{
                    margin: "0.2rem 0 0 0",
                    fontSize: "0.82rem",
                    color: "var(--text-dim, #a6adc8)",
                  }}
                >
                  Selecione uma pasta do seu computador ou crie um novo workspace agêntico
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-dim, #a6adc8)",
                fontSize: "1.25rem",
                cursor: "pointer",
                padding: "4px 8px",
                borderRadius: "6px",
              }}
              title="Fechar (Esc)"
            >
              ✕
            </button>
          </div>

          {/* Abas */}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              onClick={() => setTab("link")}
              style={{
                padding: "0.6rem 1rem",
                fontSize: "0.88rem",
                fontWeight: 600,
                color: tab === "link" ? "var(--accent, #89b4fa)" : "var(--text-dim, #a6adc8)",
                background: "transparent",
                border: "none",
                borderBottom: tab === "link" ? "2px solid var(--accent, #89b4fa)" : "2px solid transparent",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
              }}
            >
              <span>📂</span> Vincular Pasta Existente
            </button>
            <button
              type="button"
              onClick={() => setTab("create")}
              style={{
                padding: "0.6rem 1rem",
                fontSize: "0.88rem",
                fontWeight: 600,
                color: tab === "create" ? "var(--accent, #89b4fa)" : "var(--text-dim, #a6adc8)",
                background: "transparent",
                border: "none",
                borderBottom: tab === "create" ? "2px solid var(--accent, #89b4fa)" : "2px solid transparent",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
              }}
            >
              <span>✨</span> Criar Novo Projeto
            </button>
            <button
              type="button"
              onClick={() => setTab("clone")}
              style={{
                padding: "0.6rem 1rem",
                fontSize: "0.88rem",
                fontWeight: 600,
                color: tab === "clone" ? "var(--accent, #89b4fa)" : "var(--text-dim, #a6adc8)",
                background: "transparent",
                border: "none",
                borderBottom: tab === "clone" ? "2px solid var(--accent, #89b4fa)" : "2px solid transparent",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
              }}
            >
              <span>🔗</span> Clonar do Git
            </button>
          </div>
        </div>

        {/* Conteúdo do Modal */}
        <div style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
          {/* ══════════════════ TAB 1: VINCULAR PASTA EXISTENTE ══════════════════ */}
          {tab === "link" && (
            <form onSubmit={handleLinkFolder} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
              {/* Atalhos de Raízes/Unidades */}
              <div
                style={{
                  display: "flex",
                  gap: "0.75rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                {/* Botões Rápidos de Raízes/Unidades */}
                {fsData?.roots && (
                  <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                    {fsData.roots.map((root) => (
                      <button
                        key={root.path}
                        type="button"
                        onClick={() => void carregarFs(root.path)}
                        style={{
                          padding: "0.35rem 0.65rem",
                          borderRadius: "6px",
                          backgroundColor:
                            fsData.current_path === root.path
                              ? "var(--accent-dim, rgba(137, 180, 250, 0.15))"
                              : "var(--surface-2, #1e1e2e)",
                          border: "1px solid var(--border, #313244)",
                          color:
                            fsData.current_path === root.path
                              ? "var(--accent, #89b4fa)"
                              : "var(--text-dim, #a6adc8)",
                          fontSize: "0.78rem",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.3rem",
                        }}
                      >
                        <span>{root.type === "drive" ? "💽" : root.type === "projects_root" ? "⚡" : "🏠"}</span>
                        <span>{root.name.split("(")[0].trim()}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Explorador Visual de Pastas */}
              <div
                style={{
                  border: "1px solid var(--border, #313244)",
                  borderRadius: "10px",
                  backgroundColor: "var(--surface-2, #1e1e2e)",
                  overflow: "hidden",
                }}
              >
                {/* Barra de Breadcrumbs & Navegação */}
                <div
                  style={{
                    padding: "0.6rem 0.8rem",
                    backgroundColor: "rgba(0,0,0,0.2)",
                    borderBottom: "1px solid var(--border, #313244)",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    fontSize: "0.82rem",
                    overflowX: "auto",
                    whiteSpace: "nowrap",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => fsData?.parent_path && void carregarFs(fsData.parent_path)}
                    disabled={!fsData?.parent_path}
                    style={{
                      background: "none",
                      border: "1px solid var(--border, #313244)",
                      borderRadius: "4px",
                      padding: "2px 6px",
                      color: fsData?.parent_path ? "var(--text, #cdd6f4)" : "var(--text-muted, #585b70)",
                      cursor: fsData?.parent_path ? "pointer" : "default",
                      fontSize: "0.75rem",
                    }}
                    title="Subir um nível (pasta pai)"
                  >
                    ⬆️ Subir
                  </button>

                  <span style={{ color: "var(--text-dim, #6c7086)" }}>|</span>

                  {fsData?.breadcrumbs && fsData.breadcrumbs.length > 0 ? (
                    fsData.breadcrumbs.map((crumb, idx) => (
                      <React.Fragment key={crumb.path}>
                        {idx > 0 && <span style={{ color: "var(--text-dim, #6c7086)" }}>/</span>}
                        <button
                          type="button"
                          onClick={() => void carregarFs(crumb.path)}
                          style={{
                            background: "none",
                            border: "none",
                            padding: "2px 4px",
                            borderRadius: "3px",
                            color:
                              idx === fsData.breadcrumbs.length - 1
                                ? "var(--accent, #89b4fa)"
                                : "var(--text-dim, #a6adc8)",
                            fontWeight: idx === fsData.breadcrumbs.length - 1 ? 600 : 400,
                            cursor: "pointer",
                            fontSize: "0.82rem",
                          }}
                        >
                          {crumb.name}
                        </button>
                      </React.Fragment>
                    ))
                  ) : (
                    <span style={{ color: "var(--text-dim, #a6adc8)" }}>Selecione um local acima para navegar</span>
                  )}
                </div>

                {/* Lista de Pastas */}
                <div
                  style={{
                    maxHeight: "180px",
                    overflowY: "auto",
                    padding: "0.4rem",
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                    gap: "0.3rem",
                  }}
                >
                  {fsLoading ? (
                    <div style={{ gridColumn: "1 / -1", padding: "1.5rem", textAlign: "center", color: "var(--text-dim)" }}>
                      ⏳ Lendo diretórios...
                    </div>
                  ) : fsData?.directories && fsData.directories.length > 0 ? (
                    fsData.directories.map((dir) => (
                      <div
                        key={dir.path}
                        onClick={() => {
                          setSelectedPath(dir.path);
                          void inspecionar(dir.path);
                        }}
                        onDoubleClick={() => void carregarFs(dir.path)}
                        style={{
                          padding: "0.45rem 0.6rem",
                          borderRadius: "6px",
                          backgroundColor:
                            selectedPath === dir.path
                              ? "var(--accent-dim, rgba(137, 180, 250, 0.15))"
                              : "rgba(255,255,255,0.02)",
                          border:
                            selectedPath === dir.path
                              ? "1px solid var(--accent, #89b4fa)"
                              : "1px solid transparent",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "0.4rem",
                          transition: "all 0.15s ease",
                        }}
                        title={`Clique para selecionar '${dir.name}' ou duplo clique para navegar para dentro.`}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", overflow: "hidden" }}>
                          <span style={{ fontSize: "1rem" }}>📁</span>
                          <span
                            style={{
                              fontSize: "0.82rem",
                              color: "var(--text, #cdd6f4)",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                            title={dir.name}
                          >
                            {dir.name}
                          </span>
                        </div>
                        <div style={{ display: "flex", gap: "0.2rem", alignItems: "center" }}>
                          {dir.has_git && (
                            <span
                              style={{
                                fontSize: "0.65rem",
                                padding: "1px 4px",
                                borderRadius: "3px",
                                backgroundColor: "rgba(243, 139, 168, 0.15)",
                                color: "#f38ba8",
                              }}
                              title="Repositório Git"
                            >
                              git
                            </span>
                          )}
                          {dir.is_project && (
                            <span
                              style={{
                                fontSize: "0.65rem",
                                padding: "1px 4px",
                                borderRadius: "3px",
                                backgroundColor: "rgba(166, 227, 161, 0.15)",
                                color: "#a6e3a1",
                              }}
                              title="Projeto detectado (package.json, pyproject, etc.)"
                            >
                              app
                            </span>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void carregarFs(dir.path);
                            }}
                            style={{
                              background: "none",
                              border: "none",
                              color: "var(--text-dim, #a6adc8)",
                              fontSize: "0.75rem",
                              cursor: "pointer",
                              padding: "2px",
                              opacity: 0.7,
                            }}
                            title="Entrar na pasta"
                          >
                            ➔
                          </button>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ gridColumn: "1 / -1", padding: "1rem", textAlign: "center", color: "var(--text-dim)", fontSize: "0.82rem" }}>
                      Nenhuma subpasta editável nesta pasta.
                    </div>
                  )}
                </div>
                {fsData?.truncated && (
                  <div
                    style={{
                      padding: "0.4rem 0.6rem",
                      fontSize: "0.75rem",
                      color: "var(--text-dim, #a6adc8)",
                      textAlign: "center",
                    }}
                  >
                    Mostrando 120 de {fsData.total_directories} subpastas — digite ou navegue para
                    dentro para ver o restante.
                  </div>
                )}
              </div>

              {/* Input manual do caminho absoluto com auto-inspeção */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.3rem" }}>
                  <label style={{ fontSize: "0.82rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                    Caminho ou Nome da Pasta:
                  </label>
                  <span style={{ fontSize: "0.72rem", color: "var(--text-dim, #6c7086)" }}>
                    💡 Digite o nome da pasta (ex: Sorteador) ou o caminho Windows
                  </span>
                </div>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <input
                    type="text"
                    value={selectedPath}
                    onChange={(e) => {
                      setSelectedPath(e.target.value);
                      void inspecionar(e.target.value);
                    }}
                    placeholder="ex: Sorteador ou C:\Users\leona\Documents\Projetos\Sorteador"
                    style={{
                      flex: 1,
                      padding: "0.6rem 0.8rem",
                      borderRadius: "8px",
                      backgroundColor: "var(--surface-2, #1e1e2e)",
                      border: "1px solid var(--border, #313244)",
                      color: "var(--text, #cdd6f4)",
                      fontFamily: "var(--font-mono, monospace)",
                      fontSize: "0.85rem",
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => void carregarFs(selectedPath)}
                    style={{
                      padding: "0.6rem 0.9rem",
                      borderRadius: "8px",
                      backgroundColor: "var(--surface-3, #313244)",
                      border: "1px solid var(--border, #45475a)",
                      color: "var(--text, #cdd6f4)",
                      fontSize: "0.82rem",
                      cursor: "pointer",
                      fontWeight: 600,
                    }}
                  >
                    Navegar
                  </button>
                </div>
              </div>

              {/* Card de Inspeção em Tempo Real (Live Preview da Stack) */}
              {inspecting ? (
                <div style={{ padding: "1rem", textAlign: "center", color: "var(--text-dim)", fontSize: "0.85rem" }}>
                  🔍 Inspecionando stack tecnológica da pasta...
                </div>
              ) : signature ? (
                <div
                  style={{
                    backgroundColor: "rgba(137, 180, 250, 0.05)",
                    border: "1px solid rgba(137, 180, 250, 0.25)",
                    borderRadius: "10px",
                    padding: "0.9rem 1.1rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.5rem",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 700, color: "var(--text, #cdd6f4)", fontSize: "0.95rem" }}>
                      ✨ {signature.name}
                    </span>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        padding: "2px 8px",
                        borderRadius: "12px",
                        backgroundColor: "rgba(166, 227, 161, 0.2)",
                        color: "#a6e3a1",
                        fontWeight: 600,
                      }}
                    >
                      {signature.primary_language}
                    </span>
                  </div>

                  <div style={{ fontSize: "0.76rem", color: "var(--text-dim, #6c7086)", fontFamily: "var(--font-mono, monospace)" }}>
                    📍 Localização: {signature.path}
                  </div>

                  <p style={{ fontSize: "0.82rem", color: "var(--text-dim, #a6adc8)", margin: 0 }}>
                    {signature.summary || "Projeto detectado no caminho especificado."}
                  </p>


                  <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginTop: "0.2rem" }}>
                    {signature.frameworks.map((fw) => (
                      <span
                        key={fw}
                        style={{
                          fontSize: "0.72rem",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          backgroundColor: "var(--surface-3, #313244)",
                          color: "var(--accent, #89b4fa)",
                        }}
                      >
                        ⚛️ {fw}
                      </span>
                    ))}
                    {signature.has_docker && (
                      <span
                        style={{
                          fontSize: "0.72rem",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          backgroundColor: "var(--surface-3, #313244)",
                          color: "#89dceb",
                        }}
                      >
                        🐳 Docker
                      </span>
                    )}
                    {signature.has_git && (
                      <span
                        style={{
                          fontSize: "0.72rem",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          backgroundColor: "var(--surface-3, #313244)",
                          color: "#fab387",
                        }}
                      >
                        🐙 Git
                      </span>
                    )}
                    {signature.build_system && signature.build_system !== "unknown" && (
                      <span
                        style={{
                          fontSize: "0.72rem",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          backgroundColor: "var(--surface-3, #313244)",
                          color: "#cba6f7",
                        }}
                      >
                        ⚙️ {signature.build_system}
                      </span>
                    )}
                  </div>
                </div>
              ) : null}

              {/* Botões de Ação */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  onClick={onClose}
                  style={{
                    padding: "0.65rem 1.25rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text-dim, #a6adc8)",
                    fontSize: "0.88rem",
                    cursor: "pointer",
                  }}
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={linking || !selectedPath.trim()}
                  style={{
                    padding: "0.65rem 1.5rem",
                    borderRadius: "8px",
                    background: "var(--accent-gradient, linear-gradient(135deg, #89b4fa, #b4befe))",
                    color: "#11111b",
                    border: "none",
                    fontSize: "0.88rem",
                    fontWeight: 700,
                    cursor: linking || !selectedPath.trim() ? "not-allowed" : "pointer",
                    boxShadow: "0 4px 15px rgba(137, 180, 250, 0.3)",
                  }}
                >
                  {linking ? "Vinculando..." : "🚀 Vincular e Abrir Projeto"}
                </button>
              </div>
            </form>
          )}

          {/* ══════════════════ TAB 2: CRIAR NOVO PROJETO ══════════════════ */}
          {tab === "create" && (
            <form onSubmit={handleCreateProject} style={{ display: "flex", flexDirection: "column", gap: "1.1rem" }}>
              <div>
                <label style={{ display: "block", marginBottom: "0.3rem", fontSize: "0.85rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                  Nome da Pasta do Projeto *
                </label>
                <input
                  type="text"
                  required
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="ex: meu-microsservico ou backend-api"
                  style={{
                    width: "100%",
                    padding: "0.65rem 0.8rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text, #cdd6f4)",
                    fontSize: "0.9rem",
                  }}
                />
              </div>

              <div>
                <label style={{ display: "block", marginBottom: "0.3rem", fontSize: "0.85rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                  Descrição / Instruções do Projeto (Opcional)
                </label>
                <textarea
                  rows={2}
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="Descreva o propósito e convenções do projeto..."
                  style={{
                    width: "100%",
                    padding: "0.6rem 0.8rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text, #cdd6f4)",
                    fontSize: "0.85rem",
                    resize: "vertical",
                  }}
                />
              </div>

              <div>
                <label style={{ display: "block", marginBottom: "0.3rem", fontSize: "0.85rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                  Ecossistema / Linguagem Principal
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.5rem" }}>
                  {[
                    { id: "python", label: "🐍 Python (FastAPI / uv)", desc: ".venv + pyproject" },
                    { id: "typescript", label: "⚛️ TypeScript / React", desc: "Next.js + Node" },
                    { id: "go", label: "🐹 Go / Golang", desc: "go.mod" },
                    { id: "rust", label: "🦀 Rust", desc: "Cargo.toml" },
                    { id: "java", label: "☕ Java", desc: "Maven / Gradle" },
                    { id: "generic", label: "📁 Projeto Genérico", desc: "Sem template" },
                  ].map((lang) => (
                    <button
                      key={lang.id}
                      type="button"
                      onClick={() => setNewLanguage(lang.id)}
                      style={{
                        padding: "0.6rem",
                        borderRadius: "8px",
                        backgroundColor:
                          newLanguage === lang.id
                            ? "var(--accent-dim, rgba(137, 180, 250, 0.15))"
                            : "var(--surface-2, #1e1e2e)",
                        border:
                          newLanguage === lang.id
                            ? "1px solid var(--accent, #89b4fa)"
                            : "1px solid var(--border, #313244)",
                        color: newLanguage === lang.id ? "var(--accent, #89b4fa)" : "var(--text, #cdd6f4)",
                        textAlign: "left",
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ fontWeight: 600, fontSize: "0.82rem" }}>{lang.label}</div>
                      <div style={{ fontSize: "0.72rem", color: "var(--text-dim, #a6adc8)", marginTop: "2px" }}>
                        {lang.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "var(--text, #cdd6f4)", fontSize: "0.85rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={newInitGit}
                    onChange={(e) => setNewInitGit(e.target.checked)}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent, #89b4fa)", cursor: "pointer" }}
                  />
                  <span>🌱 Inicializar repositório Git local automaticamente (`git init`)</span>
                </label>

                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "var(--text, #cdd6f4)", fontSize: "0.85rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={newCreateGithub}
                    onChange={(e) => setNewCreateGithub(e.target.checked)}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent, #89b4fa)", cursor: "pointer" }}
                  />
                  <span>🔒 Criar repositório remoto **PRIVADO** no GitHub automaticamente</span>
                </label>
              </div>

              <div>
                <label style={{ display: "block", marginBottom: "0.3rem", fontSize: "0.82rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                  Limite de Orçamento Mensal USD (Opcional)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={newBudgetLimit}
                  onChange={(e) => setNewBudgetLimit(e.target.value)}
                  placeholder="ex: 50.00"
                  style={{
                    width: "100%",
                    padding: "0.55rem 0.8rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text, #cdd6f4)",
                    fontSize: "0.85rem",
                  }}
                />
              </div>

              {/* Botões de Ação */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  onClick={onClose}
                  style={{
                    padding: "0.65rem 1.25rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text-dim, #a6adc8)",
                    fontSize: "0.88rem",
                    cursor: "pointer",
                  }}
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={creating || !newName.trim()}
                  style={{
                    padding: "0.65rem 1.5rem",
                    borderRadius: "8px",
                    background: "var(--accent-gradient, linear-gradient(135deg, #89b4fa, #b4befe))",
                    color: "#11111b",
                    border: "none",
                    fontSize: "0.88rem",
                    fontWeight: 700,
                    cursor: creating || !newName.trim() ? "not-allowed" : "pointer",
                    boxShadow: "0 4px 15px rgba(137, 180, 250, 0.3)",
                  }}
                >
                  {creating ? "Criando..." : "✨ Criar e Inicializar"}
                </button>
              </div>
            </form>
          )}

          {/* ══════════════════ TAB 3: CLONAR DO GIT ══════════════════ */}
          {tab === "clone" && (
            <form onSubmit={handleCloneProject} style={{ display: "flex", flexDirection: "column", gap: "1.1rem" }}>
              <div>
                <label style={{ display: "block", marginBottom: "0.3rem", fontSize: "0.85rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                  URL do Repositório Git (HTTPS / SSH) *
                </label>
                <input
                  type="url"
                  required
                  value={cloneUrl}
                  onChange={(e) => setCloneUrl(e.target.value)}
                  placeholder="https://github.com/usuario/repositorio.git"
                  style={{
                    width: "100%",
                    padding: "0.65rem 0.8rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text, #cdd6f4)",
                    fontSize: "0.9rem",
                  }}
                />
              </div>

              <div>
                <label style={{ display: "block", marginBottom: "0.3rem", fontSize: "0.85rem", color: "var(--text-dim, #a6adc8)", fontWeight: 500 }}>
                  Nome da Pasta Local (Opcional — deriva da URL se vazio)
                </label>
                <input
                  type="text"
                  value={cloneName}
                  onChange={(e) => setCloneName(e.target.value)}
                  placeholder="ex: meu-app"
                  style={{
                    width: "100%",
                    padding: "0.65rem 0.8rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text, #cdd6f4)",
                    fontSize: "0.9rem",
                  }}
                />
              </div>

              <div
                style={{
                  backgroundColor: "rgba(137, 180, 250, 0.05)",
                  border: "1px solid rgba(137, 180, 250, 0.2)",
                  borderRadius: "8px",
                  padding: "0.8rem 1rem",
                  fontSize: "0.82rem",
                  color: "var(--text-dim, #a6adc8)",
                }}
              >
                💡 O repositório será inicializado em <code>PROJECTS_ROOT</code> com a branch principal configurada e o remote <code>origin</code> apontando para a URL informada.
              </div>

              {/* Botões de Ação */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  onClick={onClose}
                  style={{
                    padding: "0.65rem 1.25rem",
                    borderRadius: "8px",
                    backgroundColor: "var(--surface-2, #1e1e2e)",
                    border: "1px solid var(--border, #313244)",
                    color: "var(--text-dim, #a6adc8)",
                    fontSize: "0.88rem",
                    cursor: "pointer",
                  }}
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={cloning || !cloneUrl.trim()}
                  style={{
                    padding: "0.65rem 1.5rem",
                    borderRadius: "8px",
                    background: "var(--accent-gradient, linear-gradient(135deg, #89b4fa, #b4befe))",
                    color: "#11111b",
                    border: "none",
                    fontSize: "0.88rem",
                    fontWeight: 700,
                    cursor: cloning || !cloneUrl.trim() ? "not-allowed" : "pointer",
                    boxShadow: "0 4px 15px rgba(137, 180, 250, 0.3)",
                  }}
                >
                  {cloning ? "Clonando..." : "🔗 Clonar e Abrir"}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
