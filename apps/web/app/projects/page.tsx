"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { LinkProjectModal } from "@/components/ide/LinkProjectModal";
import { deleteProject, listProjects, ProjectRecord } from "@/lib/api/projects";

type SortKey = "name" | "updated_at";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalTab, setModalTab] = useState<"link" | "create" | "clone" | null>(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("updated_at");
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null);
  const { addToast } = useToast();

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await listProjects();
      setProjects(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao carregar projetos: ${message}`, "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleDelete = async (proj: ProjectRecord) => {
    const apagarArquivos = confirm(
      `Remover '${proj.name}' do Eltanix Coder IDE?\n\n` +
        "OK = remove só o cadastro (arquivos continuam no disco).\n" +
        "Cancelar = aborta a remoção."
    );
    if (!apagarArquivos) return;
    const tambemApagarDisco = confirm(
      `Também apagar a pasta '${proj.local_path}' do disco?\n\n` +
        "Isso é IRREVERSÍVEL. OK apaga os arquivos; Cancelar mantém-os (só remove o cadastro)."
    );
    setDeletingSlug(proj.slug);
    try {
      await deleteProject(proj.slug, tambemApagarDisco);
      addToast(
        tambemApagarDisco ? "Projeto e arquivos removidos." : "Projeto removido (arquivos preservados).",
        "success"
      );
      await loadData();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao remover projeto: ${message}`, "error");
    } finally {
      setDeletingSlug(null);
    }
  };

  const termo = query.trim().toLowerCase();
  const filtrados = projects
    .filter(
      (p) =>
        !termo ||
        p.name.toLowerCase().includes(termo) ||
        p.slug.toLowerCase().includes(termo) ||
        p.description?.toLowerCase().includes(termo)
    )
    .sort((a, b) =>
      sortKey === "name"
        ? a.name.localeCompare(b.name)
        : (b.updated_at || "").localeCompare(a.updated_at || "")
    );

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "var(--bg)", color: "var(--text)" }}>
      <main style={{ maxWidth: "1280px", margin: "0 auto", padding: "2rem 1.5rem" }}>
        {/* Header Section */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "2rem",
            flexWrap: "wrap",
            gap: "1rem",
          }}
        >
          <div>
            <h1
              style={{
                fontSize: "2rem",
                fontWeight: 700,
                background: "var(--accent-gradient)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                margin: 0,
              }}
            >
              Central do Projeto
            </h1>
            <p style={{ color: "var(--text-dim)", margin: "0.5rem 0 0 0", fontSize: "0.95rem" }}>
              Cadastre e gerencie o ecossistema unificado do Eltanix Coder IDE (IDE, Segundo Cérebro, Graphify, Custos, Auditoria e Git).
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              onClick={() => setModalTab("link")}
              style={{
                padding: "0.75rem 1.25rem",
                borderRadius: "var(--radius)",
                background: "var(--surface-2)",
                color: "var(--text)",
                border: "1px solid var(--border)",
                fontWeight: 600,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <span>📂</span> Vincular Pasta do PC
            </button>
            <button
              onClick={() => setModalTab("create")}
              style={{
                padding: "0.75rem 1.25rem",
                borderRadius: "var(--radius)",
                background: "var(--btn-primary-bg, var(--surface-3))",
                color: "var(--btn-primary-text, var(--text))",
                border: "1px solid var(--btn-primary-border, var(--border))",
                fontWeight: 600,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                boxShadow: "var(--shadow-lg)",
              }}
            >
              <span>✨</span> Novo Projeto
            </button>
          </div>
        </div>

        {/* Busca & Ordenação */}
        {!loading && projects.length > 0 && (
          <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="🔎 Buscar por nome, slug ou descrição..."
              style={{
                flex: "1 1 260px",
                padding: "0.6rem 0.9rem",
                borderRadius: "var(--radius)",
                backgroundColor: "var(--surface)",
                color: "var(--text)",
                border: "1px solid var(--border)",
              }}
            />
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              style={{
                padding: "0.6rem 0.9rem",
                borderRadius: "var(--radius)",
                backgroundColor: "var(--surface)",
                color: "var(--text)",
                border: "1px solid var(--border)",
              }}
            >
              <option value="updated_at">Mais recentes</option>
              <option value="name">Nome (A-Z)</option>
            </select>
          </div>
        )}

        {/* Loading / Grid */}
        {loading ? (
          <div style={{ padding: "4rem", textAlign: "center", color: "var(--text-muted)" }}>
            Carregando projetos...
          </div>
        ) : projects.length === 0 ? (
          <div
            style={{
              padding: "4rem 2rem",
              textAlign: "center",
              backgroundColor: "var(--surface)",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--border)",
            }}
          >
            <span style={{ fontSize: "3rem" }}>🚀</span>
            <h3 style={{ marginTop: "1rem", color: "var(--text)" }}>Nenhum projeto encontrado</h3>
            <p style={{ color: "var(--text-dim)", maxWidth: "500px", margin: "0.5rem auto 1.5rem" }}>
              Vincule qualquer pasta do seu computador (Windows/Linux/macOS) ou crie um novo projeto com suporte agêntico.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center" }}>
              <button
                onClick={() => setModalTab("link")}
                style={{
                  padding: "0.6rem 1.2rem",
                  borderRadius: "var(--radius)",
                  background: "var(--surface-2)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                📂 Vincular Pasta do PC
              </button>
              <button
                onClick={() => setModalTab("create")}
                style={{
                  padding: "0.6rem 1.2rem",
                  borderRadius: "var(--radius)",
                  background: "var(--accent)",
                  color: "#000",
                  border: "none",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                ✨ Criar Novo Projeto
              </button>
            </div>
          </div>
        ) : filtrados.length === 0 ? (
          <div
            style={{
              padding: "3rem 2rem",
              textAlign: "center",
              backgroundColor: "var(--surface)",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--border)",
              color: "var(--text-dim)",
            }}
          >
            Nenhum projeto corresponde a "{query}".
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(350px, 1fr))",
              gap: "1.5rem",
            }}
          >
            {filtrados.map((proj) => (
              <div
                key={proj.slug}
                style={{
                  backgroundColor: "var(--surface)",
                  borderRadius: "var(--radius-lg)",
                  border: "1px solid var(--border)",
                  padding: "1.5rem",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  transition: "all 0.2s ease",
                  boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                    <div>
                      <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 600, color: "var(--text)" }}>
                        {proj.name}
                      </h3>
                      <span style={{ fontSize: "0.8rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                        {proj.slug}
                      </span>
                    </div>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        padding: "0.25rem 0.6rem",
                        borderRadius: "12px",
                        backgroundColor: "var(--accent-dim)",
                        color: "var(--accent)",
                        fontWeight: 600,
                      }}
                    >
                      {proj.default_branch || "main"}
                    </span>
                  </div>

                  <p
                    style={{
                      fontSize: "0.9rem",
                      color: "var(--text-dim)",
                      marginBottom: "1rem",
                      minHeight: "2.5rem",
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {proj.description || "Sem descrição cadastrada."}
                  </p>
                </div>

                <div>
                  <div
                    style={{
                      display: "flex",
                      gap: "0.5rem",
                      flexWrap: "wrap",
                      marginBottom: "1.25rem",
                      fontSize: "0.8rem",
                    }}
                  >
                    {proj.git_url && (
                      <span style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", backgroundColor: "var(--surface-2)", color: "var(--text-dim)" }}>
                        🔗 Git Remote
                      </span>
                    )}
                    {proj.budget_limit_usd != null && (
                      <span style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", backgroundColor: "var(--warn-dim)", color: "var(--warn)" }}>
                        💰 Orçamento: ${proj.budget_limit_usd.toFixed(2)} USD
                      </span>
                    )}
                    {proj.local_path_exists === false && (
                      <span style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", backgroundColor: "var(--danger-dim, rgba(229,72,77,0.15))", color: "var(--danger, #e5484d)" }}>
                        ⚠️ Pasta não encontrada
                      </span>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: "0.75rem" }}>
                    <Link
                      href={`/projects/${encodeURIComponent(proj.slug)}`}
                      style={{
                        flex: 1,
                        textAlign: "center",
                        padding: "0.6rem",
                        borderRadius: "var(--radius)",
                        backgroundColor: "var(--surface-2)",
                        color: "var(--text)",
                        textDecoration: "none",
                        fontWeight: 600,
                        fontSize: "0.9rem",
                        border: "1px solid var(--border)",
                      }}
                    >
                      Hub 360°
                    </Link>
                    <Link
                      href={`/ide?project=${encodeURIComponent(proj.slug)}`}
                      style={{
                        flex: 1,
                        textAlign: "center",
                        padding: "0.6rem",
                        borderRadius: "var(--radius)",
                        background: "var(--accent-gradient)",
                        color: "#fff",
                        textDecoration: "none",
                        fontWeight: 600,
                        fontSize: "0.9rem",
                      }}
                    >
                      Abrir IDE
                    </Link>
                    {proj.my_role === "owner" && (
                      <button
                        onClick={() => handleDelete(proj)}
                        disabled={deletingSlug === proj.slug}
                        title="Remover projeto"
                        style={{
                          padding: "0.6rem 0.75rem",
                          borderRadius: "var(--radius)",
                          backgroundColor: "var(--surface-2)",
                          color: "var(--danger, #e5484d)",
                          border: "1px solid var(--border)",
                          fontWeight: 600,
                          cursor: deletingSlug === proj.slug ? "default" : "pointer",
                        }}
                      >
                        {deletingSlug === proj.slug ? "…" : "🗑️"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Modal Unificado de Vinculação / Criação / Clone */}
        {modalTab && (
          <LinkProjectModal
            initialTab={modalTab}
            onClose={() => setModalTab(null)}
            onProjectOpened={(slug) => {
              setModalTab(null);
              loadData();
              window.location.href = `/ide?project=${encodeURIComponent(slug)}`;
            }}
          />
        )}
      </main>
    </div>
  );
}
