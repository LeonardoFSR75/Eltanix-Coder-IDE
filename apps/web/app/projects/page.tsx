"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { createProject, listProjects, ProjectRecord } from "@/lib/api/projects";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [budgetLimit, setBudgetLimit] = useState("");
  const [submitting, setSubmitting] = useState(false);
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

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setSubmitting(true);
    try {
      const created = await createProject({
        name: name.trim(),
        description: description.trim(),
        git_url: gitUrl.trim() || undefined,
        budget_limit_usd: budgetLimit ? parseFloat(budgetLimit) : undefined,
      });
      addToast(`Projeto '${created.name}' cadastrado com sucesso!`, "success");
      setShowModal(false);
      setName("");
      setDescription("");
      setGitUrl("");
      setBudgetLimit("");
      loadData();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Falha ao cadastrar projeto: ${message}`, "error");
    } finally {
      setSubmitting(false);
    }
  };

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
              Cadastre e gerencie o ecossistema unificado do SicoobitoCode (IDE, Segundo Cérebro, Graphify, Custos, Auditoria e Git).
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
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
              border: "1px border var(--border)",
            }}
          >
            <span style={{ fontSize: "3rem" }}>🚀</span>
            <h3 style={{ marginTop: "1rem", color: "var(--text)" }}>Nenhum projeto encontrado</h3>
            <p style={{ color: "var(--text-dim)", maxWidth: "500px", margin: "0.5rem auto 1.5rem" }}>
              Crie pastas na raiz de projetos ou cadastre um novo projeto para gerenciar todo o ambiente agêntico.
            </p>
            <button
              onClick={() => setShowModal(true)}
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
              Cadastrar Projeto
            </button>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(350px, 1fr))",
              gap: "1.5rem",
            }}
          >
            {projects.map((proj) => (
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
                    {proj.budget_limit_usd && (
                      <span style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", backgroundColor: "var(--warn-dim)", color: "var(--warn)" }}>
                        💰 Orçamento: ${proj.budget_limit_usd.toFixed(2)} USD
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
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Modal de Cadastro */}
        {showModal && (
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "rgba(0,0,0,0.75)",
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              zIndex: 1000,
              padding: "1rem",
            }}
          >
            <div
              style={{
                backgroundColor: "var(--surface)",
                borderRadius: "var(--radius-lg)",
                border: "1px solid var(--border)",
                padding: "2rem",
                width: "100%",
                maxWidth: "500px",
                boxShadow: "var(--shadow-lg)",
              }}
            >
              <h2 style={{ margin: "0 0 1.5rem 0", color: "var(--text)", fontSize: "1.4rem" }}>
                ✨ Cadastrar Novo Projeto
              </h2>
              <form onSubmit={handleCreate}>
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.9rem" }}>
                    Nome do Projeto *
                  </label>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="ex: meu-sistema-v2"
                    style={{
                      width: "100%",
                      padding: "0.625rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      color: "var(--text)",
                    }}
                  />
                </div>

                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.9rem" }}>
                    Descrição / Objetivos do Agente
                  </label>
                  <textarea
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Descreva o propósito e convenções do projeto..."
                    style={{
                      width: "100%",
                      padding: "0.625rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      color: "var(--text)",
                      resize: "vertical",
                    }}
                  />
                </div>

                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.9rem" }}>
                    URL do Repositório Git (Opcional)
                  </label>
                  <input
                    type="url"
                    value={gitUrl}
                    onChange={(e) => setGitUrl(e.target.value)}
                    placeholder="https://github.com/org/repo.git"
                    style={{
                      width: "100%",
                      padding: "0.625rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      color: "var(--text)",
                    }}
                  />
                </div>

                <div style={{ marginBottom: "1.5rem" }}>
                  <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.9rem" }}>
                    Limite de Orçamento Mensal USD (Opcional)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    value={budgetLimit}
                    onChange={(e) => setBudgetLimit(e.target.value)}
                    placeholder="50.00"
                    style={{
                      width: "100%",
                      padding: "0.625rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      color: "var(--text)",
                    }}
                  />
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                  <button
                    type="button"
                    onClick={() => setShowModal(false)}
                    style={{
                      flex: 1,
                      padding: "0.625rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      color: "var(--text-dim)",
                      border: "1px solid var(--border)",
                      cursor: "pointer",
                    }}
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    style={{
                      flex: 1,
                      padding: "0.625rem",
                      borderRadius: "var(--radius)",
                      background: "var(--accent-gradient)",
                      color: "#fff",
                      border: "none",
                      fontWeight: 600,
                      cursor: submitting ? "not-allowed" : "pointer",
                    }}
                  >
                    {submitting ? "Criando..." : "Criar Projeto"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
