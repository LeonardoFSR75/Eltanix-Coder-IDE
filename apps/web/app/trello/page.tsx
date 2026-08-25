"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useProject } from "@/components/providers/ProjectContext";
import { useToast } from "@/components/Toast";

import {
  createProjectTrelloCard,
  deleteProjectTrelloCard,
  getProjectTrelloCards,
  updateProjectTrelloCard,
} from "@/lib/api/trello";

export type CardStatus = "todo" | "in_progress" | "review" | "done";
export type CardPriority = "high" | "medium" | "low";

export interface TrelloCard {
  id: string;
  title: string;
  description: string;
  status: CardStatus;
  priority: CardPriority;
  createdAt?: string;
  created_at?: string;
  updated_at?: string;
  created_by_agent?: boolean;
}

const COLUMNS: { id: CardStatus; title: string; icon: string; badgeColor: string }[] = [
  { id: "todo", title: "A Fazer", icon: "📝", badgeColor: "var(--accent)" },
  { id: "in_progress", title: "Em Progresso", icon: "⏳", badgeColor: "var(--warn)" },
  { id: "review", title: "Em Revisão", icon: "🔍", badgeColor: "var(--accent-purple)" },
  { id: "done", title: "Concluído", icon: "✅", badgeColor: "var(--accent-emerald)" },
];

export default function TrelloPage() {
  const { currentProject, projects, setCurrentProject } = useProject();
  const { addToast } = useToast();
  const router = useRouter();

  const [cards, setCards] = useState<TrelloCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterPriority, setFilterPriority] = useState<string>("all");
  const [showModal, setShowModal] = useState(false);
  const [editingCard, setEditingCard] = useState<TrelloCard | null>(null);

  // Form states
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<CardStatus>("todo");
  const [priority, setPriority] = useState<CardPriority>("medium");

  const loadCards = async () => {
    if (!currentProject) return;
    setLoading(true);
    try {
      const res = await getProjectTrelloCards(currentProject);
      setCards(res.cards as TrelloCard[]);
    } catch {
      // Fallback local
      const storageKey = `novaai_studio_trello_${currentProject}`;
      try {
        const stored = localStorage.getItem(storageKey);
        if (stored) setCards(JSON.parse(stored));
      } catch {
        setCards([]);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadCards();
  }, [currentProject]);

  const handleOpenModal = (card?: TrelloCard, initialStatus: CardStatus = "todo") => {
    if (card) {
      setEditingCard(card);
      setTitle(card.title);
      setDescription(card.description);
      setStatus(card.status);
      setPriority(card.priority);
    } else {
      setEditingCard(null);
      setTitle("");
      setDescription("");
      setStatus(initialStatus);
      setPriority("medium");
    }
    setShowModal(true);
  };

  const handleSaveCard = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !currentProject) return;

    try {
      if (editingCard) {
        await updateProjectTrelloCard(currentProject, editingCard.id, {
          title: title.trim(),
          description: description.trim(),
          status,
          priority,
        });
        addToast("Cartão atualizado com sucesso!", "success");
      } else {
        await createProjectTrelloCard(currentProject, {
          title: title.trim(),
          description: description.trim(),
          status,
          priority,
        });
        addToast("Novo cartão criado!", "success");
      }
      await loadCards();
    } catch (err) {
      addToast(err instanceof Error ? err.message : String(err), "error");
    }

    setShowModal(false);
  };

  const handleDeleteCard = async (cardId: string) => {
    if (!currentProject) return;
    if (!window.confirm("Deseja realmente excluir este cartão do Quadro?")) return;
    try {
      await deleteProjectTrelloCard(currentProject, cardId);
      addToast("Cartão removido.", "info");
      await loadCards();
    } catch (err) {
      addToast(err instanceof Error ? err.message : String(err), "error");
    }
  };

  const handleMoveCard = async (cardId: string, targetStatus: CardStatus) => {
    if (!currentProject) return;
    try {
      await updateProjectTrelloCard(currentProject, cardId, { status: targetStatus });
      setCards((prev) => prev.map((c) => (c.id === cardId ? { ...c, status: targetStatus } : c)));
    } catch (err) {
      addToast(err instanceof Error ? err.message : String(err), "error");
    }
  };

  const handleExecuteOnAgent = (card: TrelloCard) => {
    if (!currentProject) return;
    const taskPrompt = `${card.title}${card.description ? `: ${card.description}` : ""}`;
    router.push(`/ide?project=${encodeURIComponent(currentProject)}&task=${encodeURIComponent(taskPrompt)}`);
  };

  if (!currentProject) {
    return (
      <div className="shell">
        <div className="page-header">
          <div>
            <span className="page-badge">📋 Gestão de Tarefas & Sprints</span>
            <h1>Quadro Trello (Kanban por Projeto)</h1>
            <p>
              O Quadro Trello opera exclusivamente no contexto de um projeto. Selecione um projeto para gerenciar suas tarefas.
            </p>
          </div>
        </div>

        <div className="panel-box" style={{ textAlign: "center", padding: "48px 24px" }}>
          <div style={{ fontSize: "56px", marginBottom: "16px" }}>📁</div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, margin: "0 0 12px", color: "var(--text)" }}>
            Nenhum Projeto Selecionado
          </h2>
          <p style={{ color: "var(--text-dim)", maxWidth: "540px", margin: "0 auto 24px", lineHeight: 1.6 }}>
            Selecione um projeto abaixo para acessar seu quadro Kanban de tarefas, organizar entregas e acompanhar o progresso.
          </p>

          {projects.length > 0 ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "16px", maxWidth: "800px", margin: "0 auto" }}>
              {projects.map((p) => (
                <button
                  key={p.slug}
                  type="button"
                  onClick={() => setCurrentProject(p.slug)}
                  className="card"
                  style={{ textAlign: "left", cursor: "pointer", border: "1px solid var(--border)", transition: "all 0.2s ease" }}
                >
                  <div style={{ fontWeight: 700, color: "var(--accent)", marginBottom: "4px" }}>
                    🚀 {p.name}
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.description || p.slug}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div>
              <p style={{ color: "var(--text-muted)", fontSize: "13px", marginBottom: "16px" }}>
                Nenhum projeto foi encontrado no cadastro local.
              </p>
              <button
                type="button"
                onClick={() => router.push("/projects")}
                className="btn-primary glow-button"
              >
                🚀 Ir para a Central de Projetos
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Filtering
  const filteredCards = cards.filter((c) => {
    const matchesSearch =
      c.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesPriority = filterPriority === "all" || c.priority === filterPriority;
    return matchesSearch && matchesPriority;
  });

  const getPriorityBadge = (p: CardPriority) => {
    switch (p) {
      case "high":
        return { label: "Alta", bg: "var(--danger-dim)", color: "var(--danger)" };
      case "medium":
        return { label: "Média", bg: "var(--warn-dim)", color: "var(--warn)" };
      case "low":
        return { label: "Baixa", bg: "var(--accent-dim)", color: "var(--accent)" };
    }
  };

  return (
    <div className="shell">
      {/* Header */}
      <div className="page-header">
        <div>
          <span className="page-badge">📋 Gestão de Tarefas & Sprints</span>
          <h1>Quadro Trello — {currentProject}</h1>
          <p>Organização de cartões, prioridades e acompanhamento Kanban escopado por projeto.</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            onClick={() => handleOpenModal()}
            className="btn-primary glow-button"
          >
            ✨ Novo Cartão
          </button>
        </div>
      </div>

      {/* Filter & Search Controls */}
      <div className="panel-box" style={{ marginBottom: "20px", padding: "14px 18px", display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ flex: 1, minWidth: "220px", display: "flex", alignItems: "center", gap: "8px" }}>
          <span>🔍</span>
          <input
            type="text"
            placeholder="Buscar tarefas no quadro..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="input-text"
            style={{ width: "100%" }}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "13px", color: "var(--text-dim)" }}>Prioridade:</span>
          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value)}
            className="project-picker-select"
          >
            <option value="all">Todas as Prioridades</option>
            <option value="high">Alta Prioridade</option>
            <option value="medium">Média Prioridade</option>
            <option value="low">Baixa Prioridade</option>
          </select>
        </div>
      </div>

      {/* Kanban Board Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "16px",
          alignItems: "start",
        }}
      >
        {COLUMNS.map((col) => {
          const colCards = filteredCards.filter((c) => c.status === col.id);

          return (
            <div
              key={col.id}
              style={{
                backgroundColor: "var(--surface)",
                borderRadius: "var(--radius-lg)",
                border: "1px solid var(--border)",
                padding: "16px",
                minHeight: "500px",
                display: "flex",
                flexDirection: "column",
              }}
            >
              {/* Column Header */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  paddingBottom: "12px",
                  marginBottom: "14px",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>{col.icon}</span>
                  <strong style={{ fontSize: "14px", color: "var(--text)" }}>{col.title}</strong>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 700,
                      padding: "2px 8px",
                      borderRadius: "10px",
                      backgroundColor: "var(--surface-2)",
                      color: col.badgeColor,
                    }}
                  >
                    {colCards.length}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => handleOpenModal(undefined, col.id)}
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--accent)",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                  title={`Adicionar cartão em ${col.title}`}
                >
                  +
                </button>
              </div>

              {/* Cards List */}
              <div style={{ display: "flex", flexDirection: "column", gap: "12px", flex: 1 }}>
                {colCards.map((card) => {
                  const prio = getPriorityBadge(card.priority);

                  return (
                    <div
                      key={card.id}
                      style={{
                        backgroundColor: "var(--surface-2)",
                        borderRadius: "var(--radius)",
                        border: "1px solid var(--border)",
                        padding: "14px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "8px",
                        boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                        <strong style={{ fontSize: "14px", color: "var(--text)", lineHeight: 1.3 }}>
                          {card.title}
                        </strong>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            padding: "2px 6px",
                            borderRadius: "4px",
                            backgroundColor: prio.bg,
                            color: prio.color,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {prio.label}
                        </span>
                      </div>

                      {card.description && (
                        <p style={{ fontSize: "12px", color: "var(--text-dim)", margin: 0, lineHeight: 1.4 }}>
                          {card.description}
                        </p>
                      )}

                      {card.created_by_agent && (
                        <div style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "var(--accent-purple)", background: "rgba(168,85,247,0.12)", padding: "2px 6px", borderRadius: "4px", width: "fit-content" }}>
                          🤖 Criado pelo Agente
                        </div>
                      )}

                      {/* Card Actions Footer */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "8px", paddingTop: "8px", borderTop: "1px solid var(--border)" }}>
                        <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>{card.createdAt || card.created_at}</span>

                        <div style={{ display: "flex", gap: "4px" }}>
                          <button
                            type="button"
                            onClick={() => handleExecuteOnAgent(card)}
                            className="btn-primary-sm"
                            style={{ padding: "2px 6px", fontSize: "11px", backgroundColor: "var(--accent)", color: "#000" }}
                            title="Executar esta tarefa na IDE Agêntica"
                          >
                            🤖 Agente
                          </button>

                          {/* Shift Left */}
                          {col.id !== "todo" && (
                            <button
                              type="button"
                              onClick={() => {
                                const prevStatus: Record<CardStatus, CardStatus> = {
                                  in_progress: "todo",
                                  review: "in_progress",
                                  done: "review",
                                  todo: "todo",
                                };
                                handleMoveCard(card.id, prevStatus[col.id]);
                              }}
                              className="btn-secondary-sm"
                              style={{ padding: "2px 6px", fontSize: "11px" }}
                              title="Mover para coluna anterior"
                            >
                              ←
                            </button>
                          )}

                          {/* Shift Right */}
                          {col.id !== "done" && (
                            <button
                              type="button"
                              onClick={() => {
                                const nextStatus: Record<CardStatus, CardStatus> = {
                                  todo: "in_progress",
                                  in_progress: "review",
                                  review: "done",
                                  done: "done",
                                };
                                handleMoveCard(card.id, nextStatus[col.id]);
                              }}
                              className="btn-secondary-sm"
                              style={{ padding: "2px 6px", fontSize: "11px" }}
                              title="Mover para próxima coluna"
                            >
                              →
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => handleOpenModal(card)}
                            className="btn-secondary-sm"
                            style={{ padding: "2px 6px", fontSize: "11px" }}
                            title="Editar cartão"
                          >
                            ✏️
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteCard(card.id)}
                            className="btn-danger-sm"
                            style={{ padding: "2px 6px", fontSize: "11px" }}
                            title="Excluir cartão"
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}

                {colCards.length === 0 && (
                  <div
                    style={{
                      border: "2px dashed var(--border)",
                      borderRadius: "var(--radius)",
                      padding: "24px",
                      textAlign: "center",
                      color: "var(--text-muted)",
                      fontSize: "12px",
                    }}
                  >
                    Nenhuma tarefa
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Modal / Form */}
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
            <h2 style={{ margin: "0 0 1.5rem 0", color: "var(--text)", fontSize: "1.3rem" }}>
              {editingCard ? "✏️ Editar Cartão" : "✨ Novo Cartão Trello"}
            </h2>
            <form onSubmit={handleSaveCard}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.85rem" }}>
                  Título da Tarefa *
                </label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="ex: Implementar módulo de relatórios"
                  className="input-text"
                  style={{ width: "100%" }}
                />
              </div>

              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.85rem" }}>
                  Descrição / Detalhes
                </label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Descreva o objetivo da tarefa..."
                  className="input-text"
                  style={{ width: "100%", resize: "vertical" }}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
                <div>
                  <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.85rem" }}>
                    Coluna (Status)
                  </label>
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value as CardStatus)}
                    className="project-picker-select"
                    style={{ width: "100%" }}
                  >
                    <option value="todo">📝 A Fazer</option>
                    <option value="in_progress">⏳ Em Progresso</option>
                    <option value="review">🔍 Em Revisão</option>
                    <option value="done">✅ Concluído</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: "block", marginBottom: "0.4rem", color: "var(--text-dim)", fontSize: "0.85rem" }}>
                    Prioridade
                  </label>
                  <select
                    value={priority}
                    onChange={(e) => setPriority(e.target.value as CardPriority)}
                    className="project-picker-select"
                    style={{ width: "100%" }}
                  >
                    <option value="high">🔴 Alta</option>
                    <option value="medium">🟡 Média</option>
                    <option value="low">🔵 Baixa</option>
                  </select>
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="btn-secondary"
                >
                  Cancelar
                </button>
                <button type="submit" className="btn-primary">
                  {editingCard ? "Salvar Alterações" : "Criar Cartão"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
