"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { NoteRecord, createNote, deleteNote, listNotes, updateNote } from "@/lib/api/notes";
import { useToast } from "@/components/Toast";
import { useProject } from "@/components/providers/ProjectContext";

export default function SecondBrainPage() {
  const { addToast } = useToast();
  const { currentProject } = useProject();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [notes, setNotes] = useState<NoteRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNote, setSelectedNote] = useState<NoteRecord | null>(null);

  // Editor states
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTagFilter, setSelectedTagFilter] = useState<string | null>(null);

  const selectNote = useCallback((note: NoteRecord) => {
    setSelectedNote(note);
    setEditTitle(note.title);
    setEditContent(note.content);
    setEditTags(note.tags.join(" "));
  }, []);

  const refreshNotes = useCallback(async () => {
    try {
      const loaded = await listNotes(currentProject);
      setNotes(loaded);
      return loaded;
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao carregar notas.", "error");
      return [];
    } finally {
      setLoading(false);
    }
  }, [addToast, currentProject]);

  useEffect(() => {
    refreshNotes().then((loaded) => {
      if (loaded.length > 0) selectNote(loaded[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject]);

  // Salvar nota alterada — `links` é resolvido no servidor a partir dos
  // [[wikilinks]] no conteúdo, não calculado aqui.
  const handleSaveNote = async () => {
    if (!selectedNote) return;
    const parsedTags = editTags
      .split(" ")
      .filter((t) => t.trim().length > 0)
      .map((t) => (t.startsWith("#") ? t : `#${t}`));

    setSaving(true);
    try {
      const updated = await updateNote(selectedNote.id, {
        title: editTitle,
        content: editContent,
        tags: parsedTags,
      });
      setNotes((prev) => prev.map((n) => (n.id === updated.id ? updated : n)));
      setSelectedNote(updated);
      addToast(`Nota "${updated.title}" salva e reindexada.`, "success");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao salvar nota.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCreateNote = async () => {
    try {
      const created = await createNote({
        title: "Nova Nota de Conhecimento",
        content: "Digite seu conhecimento aqui... Use [[Nome da Nota]] para conectar conceitos.",
        tags: ["#novo"],
        project: currentProject,
      });
      setNotes((prev) => [created, ...prev]);
      selectNote(created);
      addToast("Nova nota criada.", "info");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao criar nota.", "error");
    }
  };

  const handleDeleteNote = async (id: string) => {
    try {
      await deleteNote(id);
      const updated = notes.filter((n) => n.id !== id);
      setNotes(updated);
      if (updated.length > 0) {
        selectNote(updated[0]);
      } else {
        setSelectedNote(null);
      }
      addToast("Nota removida.", "info");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao remover nota.", "error");
    }
  };

  // Desenhar Grafo Obsidian 2D no Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    if (notes.length === 0) return;

    const nodePositions: Record<string, { x: number; y: number; title: string }> = {};
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.35;

    notes.forEach((note, idx) => {
      const angle = (idx / notes.length) * Math.PI * 2;
      const x = centerX + Math.cos(angle) * radius;
      const y = centerY + Math.sin(angle) * radius;
      nodePositions[note.id] = { x, y, title: note.title };
    });

    notes.forEach((note) => {
      const fromPos = nodePositions[note.id];
      if (!fromPos) return;

      note.links.forEach((targetId) => {
        const toPos = nodePositions[targetId];
        if (toPos) {
          ctx.beginPath();
          ctx.moveTo(fromPos.x, fromPos.y);
          ctx.lineTo(toPos.x, toPos.y);
          ctx.strokeStyle = "rgba(59, 130, 246, 0.4)";
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      });
    });

    notes.forEach((note) => {
      const pos = nodePositions[note.id];
      if (!pos) return;

      const isSelected = selectedNote?.id === note.id;

      ctx.beginPath();
      ctx.arc(pos.x, pos.y, isSelected ? 18 : 12, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? "#3b82f6" : "#8b5cf6";
      ctx.fill();
      ctx.strokeStyle = isSelected ? "#60a5fa" : "#ffffff";
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = "#e2e8f0";
      ctx.font = isSelected ? "bold 12px sans-serif" : "11px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(note.title, pos.x, pos.y + 28);
    });
  }, [notes, selectedNote]);

  const filteredNotes = notes.filter((n) => {
    const matchesSearch =
      n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.content.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesTag = selectedTagFilter ? n.tags.includes(selectedTagFilter) : true;
    return matchesSearch && matchesTag;
  });

  const allTags = Array.from(new Set(notes.flatMap((n) => n.tags)));

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">📓 Gestão de Conhecimento Estilo Obsidian</span>
          <h1>Segundo Cérebro & Grafo de Notas</h1>
          <p>
            Conecte pensamentos com [[wikilinks]] e tags — persistido no backend, indexado
            para o agente buscar via <code className="inline-code">search_notes</code>.
          </p>
        </div>
        <div className="header-actions">
          <Link
            href={currentProject ? `/rag?project=${encodeURIComponent(currentProject)}` : "/rag"}
            className="btn-secondary-sm"
          >
            📚 RAG & Documentos
          </Link>
          <Link
            href={currentProject ? `/graphify?project=${encodeURIComponent(currentProject)}` : "/graphify"}
            className="btn-secondary-sm"
          >
            🕸️ Graphify Engine
          </Link>
          <button type="button" className="btn-primary glow-button" onClick={handleCreateNote}>
            + Nova Nota
          </button>
        </div>
      </div>

      <div className="obsidian-layout">
        <div className="obsidian-sidebar">
          <div className="sidebar-search">
            <input
              type="text"
              placeholder="🔍 Buscar notas e [[links]]..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input-text"
            />
          </div>

          <div className="tags-cloud">
            <span
              role="button"
              tabIndex={0}
              className={`tag-chip ${selectedTagFilter === null ? "active" : ""}`}
              onClick={() => setSelectedTagFilter(null)}
              onKeyDown={(e) => e.key === "Enter" && setSelectedTagFilter(null)}
            >
              #todas
            </span>
            {allTags.map((tag) => (
              <span
                key={tag}
                role="button"
                tabIndex={0}
                className={`tag-chip ${selectedTagFilter === tag ? "active" : ""}`}
                onClick={() => setSelectedTagFilter(selectedTagFilter === tag ? null : tag)}
                onKeyDown={(e) =>
                  e.key === "Enter" && setSelectedTagFilter(selectedTagFilter === tag ? null : tag)
                }
              >
                {tag}
              </span>
            ))}
          </div>

          <div className="notes-list">
            {loading && <p className="text-xs text-muted">Carregando…</p>}
            {!loading && filteredNotes.length === 0 && (
              <p className="text-xs text-muted">Nenhuma nota encontrada.</p>
            )}
            {filteredNotes.map((n) => (
              <div
                key={n.id}
                className={`note-item-card ${selectedNote?.id === n.id ? "active" : ""}`}
                onClick={() => selectNote(n)}
              >
                <div className="note-card-title">{n.title}</div>
                <div className="note-card-preview">{n.content.slice(0, 75)}...</div>
                <div className="note-card-tags">
                  {n.tags.map((t) => (
                    <span key={t} className="mini-tag">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="obsidian-main">
          {selectedNote ? (
            <div className="obsidian-editor-container">
              <div className="editor-toolbar">
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="editor-title-input"
                  placeholder="Título da Nota"
                />
                <div className="editor-actions">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={handleSaveNote}
                    disabled={saving}
                  >
                    {saving ? "Salvando…" : "💾 Salvar"}
                  </button>
                  <button
                    type="button"
                    className="btn-danger-sm"
                    onClick={() => handleDeleteNote(selectedNote.id)}
                  >
                    🗑️ Excluir
                  </button>
                </div>
              </div>

              <div className="editor-tags-bar">
                <label>Tags (#tag1 #tag2):</label>
                <input
                  type="text"
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                  className="input-text-sm"
                  placeholder="#ia #mcp #rag"
                />
              </div>

              <div className="editor-workspace">
                <div className="editor-pane">
                  <label className="pane-label">Editor Markdown</label>
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="markdown-textarea"
                    placeholder="Escreva com suporte a Markdown e [[wikilinks]]..."
                  />
                </div>

                <div className="preview-pane">
                  <label className="pane-label">Preview & Conexões Detectadas</label>
                  <div className="markdown-preview">
                    <h3>{editTitle}</h3>
                    <p className="whitespace-pre-wrap">{editContent}</p>

                    <div className="backlinks-box">
                      <h4>🔗 Referências & [[Wikilinks]]</h4>
                      {selectedNote.links.length > 0 ? (
                        <ul>
                          {selectedNote.links.map((linkId) => {
                            const targetNote = notes.find((n) => n.id === linkId);
                            return targetNote ? (
                              <li
                                key={linkId}
                                onClick={() => selectNote(targetNote)}
                                className="clickable-link"
                              >
                                🔗 [[{targetNote.title}]]
                              </li>
                            ) : null;
                          })}
                        </ul>
                      ) : (
                        <p className="text-muted text-sm">
                          Nenhum [[wikilink]] vinculado no momento. Salve para o servidor resolver.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="no-note-selected">Selecione ou crie uma nota no menu lateral</div>
          )}

          <div className="graph-container">
            <div className="graph-header">
              <span>🕸️ Mapa do Grafo de Conhecimento</span>
              <span className="text-xs text-muted">{notes.length} nós ativos</span>
            </div>
            <canvas ref={canvasRef} width={800} height={260} className="graph-canvas" />
          </div>
        </div>
      </div>
    </div>
  );
}
