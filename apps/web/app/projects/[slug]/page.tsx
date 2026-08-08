"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { useProject } from "@/components/providers/ProjectContext";
import { getProjectSummary, ProjectSummary, updateProject } from "@/lib/api/projects";

interface Props {
  params: Promise<{ slug: string }>;
}

export default function ProjectDetailPage({ params }: Props) {
  const { slug } = use(params);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"overview" | "second_brain" | "graphify" | "costs" | "audit">("overview");
  const [editingBudget, setEditingBudget] = useState(false);
  const [budgetVal, setBudgetVal] = useState("");
  const { addToast } = useToast();
  const { setCurrentProject } = useProject();

  // Entrar no Hub 360° de um projeto já o torna o projeto atual da app —
  // fecha o ciclo "entro pelo Hub, tudo que abro dali já sabe do projeto".
  useEffect(() => {
    setCurrentProject(slug);
  }, [slug, setCurrentProject]);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await getProjectSummary(slug);
      setSummary(data);
      setBudgetVal(data.budget_limit_usd ? String(data.budget_limit_usd) : "");
    } catch (err: any) {
      addToast(`Erro ao carregar resumo do projeto: ${err.message}`, "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [slug]);

  const handleSaveBudget = async () => {
    try {
      const updated = await updateProject(slug, {
        budget_limit_usd: budgetVal ? parseFloat(budgetVal) : undefined,
      });
      addToast("Limite de orçamento atualizado!", "success");
      setEditingBudget(false);
      loadData();
    } catch (err: any) {
      addToast(`Erro ao atualizar orçamento: ${err.message}`, "error");
    }
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", backgroundColor: "var(--bg)", color: "var(--text)" }}>
        <div style={{ padding: "4rem", textAlign: "center", color: "var(--text-muted)" }}>
          Carregando Hub 360° do Projeto...
        </div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div style={{ minHeight: "100vh", backgroundColor: "var(--bg)", color: "var(--text)" }}>
        <div style={{ padding: "4rem", textAlign: "center" }}>
          <h2>Projeto não encontrado</h2>
          <Link href="/projects" style={{ color: "var(--accent)" }}>
            Voltar para a Central de Projetos
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "var(--bg)", color: "var(--text)" }}>
      <main style={{ maxWidth: "1280px", margin: "0 auto", padding: "2rem 1.5rem" }}>
        {/* Breadcrumb & Top Bar */}
        <div style={{ marginBottom: "1.5rem" }}>
          <Link href="/projects" style={{ color: "var(--text-muted)", textDecoration: "none", fontSize: "0.9rem" }}>
            ← Central de Projetos
          </Link>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginTop: "0.5rem",
              flexWrap: "wrap",
              gap: "1rem",
            }}
          >
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <h1 style={{ margin: 0, fontSize: "2rem", fontWeight: 700, color: "var(--text)" }}>
                  {summary.name}
                </h1>
                <span
                  style={{
                    padding: "0.25rem 0.6rem",
                    borderRadius: "12px",
                    backgroundColor: "var(--accent-dim)",
                    color: "var(--accent)",
                    fontWeight: 600,
                    fontSize: "0.85rem",
                  }}
                >
                  🌿 {summary.branch || "sem branch"}
                </span>
              </div>
              <p style={{ color: "var(--text-dim)", margin: "0.25rem 0 0 0", fontSize: "0.95rem" }}>
                {summary.description || "Sem descrição"}
              </p>
            </div>

            <div style={{ display: "flex", gap: "0.75rem" }}>
              <Link
                href={`/ide?project=${encodeURIComponent(summary.slug)}`}
                style={{
                  padding: "0.75rem 1.5rem",
                  borderRadius: "var(--radius)",
                  background: "var(--accent-gradient)",
                  color: "#fff",
                  textDecoration: "none",
                  fontWeight: 600,
                  boxShadow: "var(--shadow-glow)",
                }}
              >
                💻 Abrir na IDE
              </Link>
            </div>
          </div>
        </div>

        {/* 360 Metric Highlights Bar */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "1rem",
            marginBottom: "2rem",
          }}
        >
          <div style={metricCardStyle}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-dim)" }}>Custo Total (LLM)</span>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent)" }}>
              ${summary.total_cost_usd.toFixed(4)} USD
            </span>
          </div>

          <div style={metricCardStyle}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-dim)" }}>Tokens Consumidos</span>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-purple)" }}>
              {summary.total_tokens.toLocaleString()}
            </span>
          </div>

          <div style={metricCardStyle}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-dim)" }}>Segundo Cérebro</span>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-emerald)" }}>
              {summary.notes_count} notas
            </span>
          </div>

          <div style={metricCardStyle}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-dim)" }}>Documentos (RAG)</span>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-emerald)" }}>
              {summary.documents_count}
            </span>
          </div>

          <div style={metricCardStyle}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-dim)" }}>Graphify Knowledge</span>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--warn)" }}>
              {summary.graph_nodes_count} nós | {summary.graph_edges_count} arestas
            </span>
          </div>

          <div style={metricCardStyle}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-dim)" }}>Eventos Auditoria</span>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--text)" }}>
              {summary.audit_events_count}
            </span>
          </div>
        </div>

        {/* Integrated Navigation Tabs */}
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            borderBottom: "1px solid var(--border)",
            marginBottom: "1.5rem",
          }}
        >
          {[
            { id: "overview", label: "💻 Visão Geral & Git" },
            { id: "second_brain", label: "📓 Segundo Cérebro & RAG" },
            { id: "graphify", label: "🕸️ Graphify Engine" },
            { id: "costs", label: "📊 FinOps & Custos" },
            { id: "audit", label: "🛡️ Auditoria" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              style={{
                padding: "0.75rem 1.25rem",
                background: "none",
                border: "none",
                borderBottom: activeTab === tab.id ? "2px solid var(--accent)" : "2px solid transparent",
                color: activeTab === tab.id ? "var(--accent)" : "var(--text-dim)",
                fontWeight: activeTab === tab.id ? 600 : 400,
                cursor: "pointer",
                fontSize: "0.95rem",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div style={{ backgroundColor: "var(--surface)", borderRadius: "var(--radius-lg)", border: "1px solid var(--border)", padding: "1.5rem" }}>
          {activeTab === "overview" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Detalhes do Workspace e Repositório</h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Caminho Local</label>
                  <p style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", color: "var(--text)" }}>
                    {summary.local_path}
                  </p>
                </div>

                <div>
                  <label style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Git Remote URL</label>
                  <p style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", color: "var(--text)" }}>
                    {summary.git_url || "Não configurado"}
                  </p>
                </div>
              </div>

              {summary.recent_commits.length > 0 && (
                <div style={{ marginTop: "1.5rem" }}>
                  <label style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Commits Recentes</label>
                  <ul style={{ listStyle: "none", padding: 0, margin: "0.5rem 0 0 0" }}>
                    {summary.recent_commits.map((c) => (
                      <li
                        key={c.sha}
                        style={{
                          padding: "0.5rem 0",
                          borderBottom: "1px solid var(--border)",
                          fontSize: "0.85rem",
                          display: "flex",
                          gap: "0.75rem",
                          color: "var(--text-dim)",
                        }}
                      >
                        <code style={{ color: "var(--accent)" }}>{c.sha}</code>
                        <span style={{ flex: 1, color: "var(--text)" }}>{c.message}</span>
                        <span>{c.author}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {activeTab === "second_brain" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Segundo Cérebro Vinculado</h3>
              <p style={{ color: "var(--text-dim)" }}>
                Este projeto possui {summary.notes_count} notas registradas. Você pode pesquisá-las ou criar novas notas no contexto deste projeto.
              </p>
              <Link
                href={`/second-brain?project=${encodeURIComponent(summary.slug)}`}
                style={{
                  display: "inline-block",
                  padding: "0.5rem 1rem",
                  borderRadius: "var(--radius)",
                  backgroundColor: "var(--surface-2)",
                  color: "var(--text)",
                  textDecoration: "none",
                }}
              >
                Ir para o Segundo Cérebro →
              </Link>
            </div>
          )}

          {activeTab === "graphify" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Grafo de Conhecimento do Código (Graphify)</h3>
              <p style={{ color: "var(--text-dim)" }}>
                Nós extraídos de símbolos, dependências e notas: {summary.graph_nodes_count} nós | {summary.graph_edges_count} relacionamentos.
              </p>
              <Link
                href={`/graphify?project=${encodeURIComponent(summary.slug)}`}
                style={{
                  display: "inline-block",
                  padding: "0.5rem 1rem",
                  borderRadius: "var(--radius)",
                  backgroundColor: "var(--surface-2)",
                  color: "var(--text)",
                  textDecoration: "none",
                }}
              >
                Abrir Visualizador Graphify →
              </Link>
            </div>
          )}

          {activeTab === "costs" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Gestão de Custos & Tokens</h3>
              <p style={{ color: "var(--text-dim)" }}>
                Contabilidade detalhada de consumo do gateway multi-modelo para este projeto.
              </p>
              <div style={{ marginTop: "1rem" }}>
                {editingBudget ? (
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <input
                      type="number"
                      step="0.01"
                      value={budgetVal}
                      onChange={(e) => setBudgetVal(e.target.value)}
                      placeholder="Novo orçamento USD"
                      style={{ padding: "0.5rem", borderRadius: "var(--radius)", backgroundColor: "var(--surface-2)", color: "var(--text)", border: "1px solid var(--border)" }}
                    />
                    <button onClick={handleSaveBudget} style={{ padding: "0.5rem 1rem", borderRadius: "var(--radius)", backgroundColor: "var(--accent)", color: "#000", border: "none" }}>
                      Salvar
                    </button>
                  </div>
                ) : (
                  <div>
                    <span>Orçamento Limite: ${summary.budget_limit_usd ? summary.budget_limit_usd.toFixed(2) : "Sem limite"} USD</span>
                    <button
                      onClick={() => setEditingBudget(true)}
                      style={{ marginLeft: "1rem", background: "none", border: "none", color: "var(--accent)", cursor: "pointer" }}
                    >
                      [Editar Limite]
                    </button>
                  </div>
                )}
              </div>
              <Link
                href={`/requests?project=${encodeURIComponent(summary.slug)}`}
                style={{
                  display: "inline-block",
                  marginTop: "1rem",
                  padding: "0.5rem 1rem",
                  borderRadius: "var(--radius)",
                  backgroundColor: "var(--surface-2)",
                  color: "var(--text)",
                  textDecoration: "none",
                }}
              >
                Ver Requests Detalhados →
              </Link>
            </div>
          )}

          {activeTab === "audit" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Trilha de Auditoria & Guardrails</h3>
              <p style={{ color: "var(--text-dim)" }}>
                Log de ações de ferramentas (WRITE/EXEC) e aprovações humanas neste projeto: {summary.audit_events_count} eventos gravados.
              </p>
              <Link
                href="/audit"
                style={{
                  display: "inline-block",
                  padding: "0.5rem 1rem",
                  borderRadius: "var(--radius)",
                  backgroundColor: "var(--surface-2)",
                  color: "var(--text)",
                  textDecoration: "none",
                }}
              >
                Ver Trilha Completa de Auditoria →
              </Link>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

const metricCardStyle: React.CSSProperties = {
  backgroundColor: "var(--surface)",
  borderRadius: "var(--radius-lg)",
  border: "1px solid var(--border)",
  padding: "1rem 1.25rem",
  display: "flex",
  flexDirection: "column",
  gap: "0.25rem",
};
