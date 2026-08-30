"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { useProject } from "@/components/providers/ProjectContext";
import { useAuth } from "@/components/providers/AuthContext";
import {
  addMember,
  getProjectSummary,
  listMembers,
  ProjectMember,
  ProjectSummary,
  removeMember,
  updateProject,
} from "@/lib/api/projects";
import { searchUsers, UserSearchResult } from "@/lib/api/users";

interface Props {
  params: Promise<{ slug: string }>;
}

export default function ProjectDetailPage({ params }: Props) {
  const { slug } = use(params);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  type TabType = "overview" | "second_brain" | "graphify" | "costs" | "audit" | "members";
  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [editingBudget, setEditingBudget] = useState(false);
  const [budgetVal, setBudgetVal] = useState("");
  const { addToast } = useToast();
  const { setCurrentProject } = useProject();
  const { user } = useAuth();

  // Aba "Membros" (ADR 0016, Fase 3): lista carregada à parte de `summary`
  // (que não traz colaboradores), e só uma vez — refeita depois de
  // convidar/remover alguém.
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [inviteQuery, setInviteQuery] = useState("");
  const [inviteResults, setInviteResults] = useState<UserSearchResult[]>([]);
  const [inviteSearching, setInviteSearching] = useState(false);
  const [inviteRole, setInviteRole] = useState<ProjectMember["role"]>("editor");
  const [inviting, setInviting] = useState(false);

  const loadMembers = async () => {
    setMembersLoading(true);
    try {
      setMembers(await listMembers(slug));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao carregar membros: ${message}`, "error");
    } finally {
      setMembersLoading(false);
    }
  };

  const handleSearchUsers = async () => {
    setInviteSearching(true);
    try {
      const existentes = new Set(members.map((m) => m.user_id));
      const resultados = await searchUsers(inviteQuery);
      setInviteResults(resultados.filter((u) => !existentes.has(u.id)));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao buscar usuários: ${message}`, "error");
    } finally {
      setInviteSearching(false);
    }
  };

  const handleInvite = async (userId: string) => {
    setInviting(true);
    try {
      await addMember(slug, userId, inviteRole);
      addToast("Membro adicionado!", "success");
      setInviteResults((prev) => prev.filter((u) => u.id !== userId));
      setInviteQuery("");
      await loadMembers();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao adicionar membro: ${message}`, "error");
    } finally {
      setInviting(false);
    }
  };

  const handleRemoveMember = async (userId: string, label: string) => {
    if (!confirm(`Remover ${label} deste projeto?`)) return;
    try {
      await removeMember(slug, userId);
      addToast("Membro removido.", "success");
      await loadMembers();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao remover membro: ${message}`, "error");
    }
  };

  const handleChangeRole = async (userId: string, role: ProjectMember["role"]) => {
    try {
      await addMember(slug, userId, role);
      addToast("Papel atualizado.", "success");
      await loadMembers();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao mudar papel: ${message}`, "error");
    }
  };

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
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao carregar resumo do projeto: ${message}`, "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    loadMembers();
  }, [slug]);

  const handleSaveBudget = async () => {
    try {
      const updated = await updateProject(slug, {
        budget_limit_usd: budgetVal ? parseFloat(budgetVal) : undefined,
      });
      addToast("Limite de orçamento atualizado!", "success");
      setEditingBudget(false);
      loadData();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast(`Erro ao atualizar orçamento: ${message}`, "error");
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

            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <Link
                href={`/trello?project=${encodeURIComponent(summary.slug)}`}
                style={{
                  padding: "0.75rem 1.25rem",
                  borderRadius: "var(--radius)",
                  backgroundColor: "var(--surface-2)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  textDecoration: "none",
                  fontWeight: 600,
                }}
              >
                📋 Quadro Trello
              </Link>
              <Link
                href={`/settings/git?project=${encodeURIComponent(summary.slug)}`}
                style={{
                  padding: "0.75rem 1.25rem",
                  borderRadius: "var(--radius)",
                  backgroundColor: "var(--surface-2)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  textDecoration: "none",
                  fontWeight: 600,
                }}
              >
                🐙 Configurar Git
              </Link>
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
            { id: "members", label: `👥 Membros${members.length ? ` (${members.length})` : ""}` },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as TabType)}
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

              <div style={{ marginTop: "1.5rem" }}>
                <Link
                  href={`/settings/git?project=${encodeURIComponent(summary.slug)}`}
                  style={{
                    display: "inline-block",
                    padding: "0.5rem 1rem",
                    borderRadius: "var(--radius)",
                    backgroundColor: "var(--surface-2)",
                    color: "var(--text)",
                    textDecoration: "none",
                    border: "1px solid var(--border)",
                  }}
                >
                  ⚙️ Gerenciar Identidade & Remotos Git do Projeto →
                </Link>
              </div>
            </div>
          )}

          {activeTab === "second_brain" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Segundo Cérebro & Base de Conhecimento</h3>
              <p style={{ color: "var(--text-dim)" }}>
                Este projeto possui {summary.notes_count} notas e {summary.documents_count} documentos vetorizados.
              </p>
              <div style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
                <Link
                  href={`/second-brain?project=${encodeURIComponent(summary.slug)}`}
                  style={{
                    padding: "0.5rem 1rem",
                    borderRadius: "var(--radius)",
                    backgroundColor: "var(--surface-2)",
                    color: "var(--text)",
                    textDecoration: "none",
                    border: "1px solid var(--border)",
                  }}
                >
                  📓 Notas Obsidian & Wikilinks →
                </Link>
                <Link
                  href={`/rag?project=${encodeURIComponent(summary.slug)}`}
                  style={{
                    padding: "0.5rem 1rem",
                    borderRadius: "var(--radius)",
                    backgroundColor: "var(--surface-2)",
                    color: "var(--text)",
                    textDecoration: "none",
                    border: "1px solid var(--border)",
                  }}
                >
                  📚 Documentos PDFs & Busca RAG →
                </Link>
              </div>
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

          {activeTab === "members" && (
            <div>
              <h3 style={{ marginTop: 0 }}>Colaboradores do Projeto</h3>
              <p style={{ color: "var(--text-dim)" }}>
                Papéis: <strong>viewer</strong> (só leitura), <strong>editor</strong> (lê e escreve) e{" "}
                <strong>owner</strong> (também gerencia membros e pode apagar o projeto).
              </p>

              <div style={{ marginTop: "1.5rem" }}>
                <label style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Convidar por username</label>
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
                  <input
                    type="text"
                    value={inviteQuery}
                    onChange={(e) => setInviteQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSearchUsers()}
                    placeholder="Buscar usuário..."
                    style={{
                      padding: "0.5rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                      minWidth: "220px",
                    }}
                  />
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as ProjectMember["role"])}
                    style={{
                      padding: "0.5rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <option value="viewer">viewer</option>
                    <option value="editor">editor</option>
                    <option value="owner">owner</option>
                  </select>
                  <button
                    onClick={handleSearchUsers}
                    disabled={inviteSearching}
                    style={{
                      padding: "0.5rem 1rem",
                      borderRadius: "var(--radius)",
                      backgroundColor: "var(--surface-2)",
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                      cursor: inviteSearching ? "default" : "pointer",
                    }}
                  >
                    {inviteSearching ? "Buscando..." : "🔎 Buscar"}
                  </button>
                </div>

                {inviteResults.length > 0 && (
                  <ul style={{ listStyle: "none", padding: 0, margin: "0.75rem 0 0 0" }}>
                    {inviteResults.map((u) => (
                      <li
                        key={u.id}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          padding: "0.5rem 0.75rem",
                          borderRadius: "var(--radius)",
                          backgroundColor: "var(--surface-2)",
                          marginBottom: "0.4rem",
                        }}
                      >
                        <span>
                          {u.display_name || u.username}{" "}
                          <span style={{ color: "var(--text-dim)", fontSize: "0.85rem" }}>@{u.username}</span>
                        </span>
                        <button
                          onClick={() => handleInvite(u.id)}
                          disabled={inviting}
                          style={{
                            padding: "0.3rem 0.75rem",
                            borderRadius: "var(--radius)",
                            backgroundColor: "var(--accent)",
                            color: "#000",
                            border: "none",
                            cursor: inviting ? "default" : "pointer",
                          }}
                        >
                          + Adicionar como {inviteRole}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div style={{ marginTop: "2rem" }}>
                <label style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                  Membros atuais {membersLoading ? "(carregando...)" : `(${members.length})`}
                </label>
                <ul style={{ listStyle: "none", padding: 0, margin: "0.5rem 0 0 0" }}>
                  {members.map((m) => (
                    <li
                      key={m.user_id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "0.6rem 0.75rem",
                        borderBottom: "1px solid var(--border)",
                        gap: "0.75rem",
                        flexWrap: "wrap",
                      }}
                    >
                      <span>
                        {m.display_name || m.username || m.user_id}
                        {m.username && (
                          <span style={{ color: "var(--text-dim)", fontSize: "0.85rem" }}> @{m.username}</span>
                        )}
                        {m.user_id === user?.id && (
                          <span style={{ color: "var(--accent)", fontSize: "0.8rem" }}> (você)</span>
                        )}
                      </span>
                      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                        <select
                          value={m.role}
                          onChange={(e) => handleChangeRole(m.user_id, e.target.value as ProjectMember["role"])}
                          style={{
                            padding: "0.3rem 0.5rem",
                            borderRadius: "var(--radius)",
                            backgroundColor: "var(--surface-2)",
                            color: "var(--text)",
                            border: "1px solid var(--border)",
                          }}
                        >
                          <option value="viewer">viewer</option>
                          <option value="editor">editor</option>
                          <option value="owner">owner</option>
                        </select>
                        <button
                          onClick={() => handleRemoveMember(m.user_id, m.display_name || m.username || m.user_id)}
                          style={{
                            background: "none",
                            border: "none",
                            color: "var(--danger, #e5484d)",
                            cursor: "pointer",
                          }}
                        >
                          Remover
                        </button>
                      </div>
                    </li>
                  ))}
                  {!membersLoading && members.length === 0 && (
                    <li style={{ color: "var(--text-dim)", padding: "0.5rem 0" }}>
                      Nenhum membro cadastrado ainda — projeto descoberto no disco sem dono atribuído.
                    </li>
                  )}
                </ul>
              </div>
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
