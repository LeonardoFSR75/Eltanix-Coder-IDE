"use client";

import React, { useEffect, useRef, useState } from "react";
import { LocalDB, Note } from "@/lib/db";
import { ChromaClient } from "@/lib/chroma";
import { useToast } from "@/components/Toast";

export default function SecondBrainPage() {
  const { addToast } = useToast();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [notes, setNotes] = useState<Note[]>([]);
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);

  // Editor states
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTagFilter, setSelectedTagFilter] = useState<string | null>(null);

  useEffect(() => {
    const loadedNotes = LocalDB.getNotes();
    setNotes(loadedNotes);
    if (loadedNotes.length > 0) {
      selectNote(loadedNotes[0]);
    }
  }, []);

  const selectNote = (note: Note) => {
    setSelectedNote(note);
    setEditTitle(note.title);
    setEditContent(note.content);
    setEditTags(note.tags.join(" "));
  };

  // Salvar nota alterada
  const handleSaveNote = () => {
    if (!selectedNote) return;

    // Detectar [[wikilinks]] no conteúdo
    const wikiLinkMatches = editContent.match(/\[\[(.*?)\]\]/g) || [];
    const extractedLinks = wikiLinkMatches.map((m) => m.replace(/\[\[|\]\]/g, ""));

    // Encontrar IDs de notas vinculadas
    const linkIds: string[] = [];
    extractedLinks.forEach((linkTitle) => {
      const match = notes.find((n) => n.title.toLowerCase() === linkTitle.toLowerCase());
      if (match) linkIds.push(match.id);
    });

    const parsedTags = editTags
      .split(" ")
      .filter((t) => t.trim().length > 0)
      .map((t) => (t.startsWith("#") ? t : `#${t}`));

    const updatedNote: Note = {
      ...selectedNote,
      title: editTitle,
      content: editContent,
      tags: parsedTags,
      links: linkIds,
      updatedAt: new Date().toISOString(),
    };

    const updatedNotesList = notes.map((n) => (n.id === updatedNote.id ? updatedNote : n));
    setNotes(updatedNotesList);
    setSelectedNote(updatedNote);
    LocalDB.saveNotes(updatedNotesList);

    // ✅ INTEGRAÇÃO RAG/CHROMADB: Auto-vetorizar nota no banco de vetores
    ChromaClient.addNoteToChroma(updatedNote.id, updatedNote.title, updatedNote.content);

    // ✅ INTEGRAÇÃO AUDITORIA: Registra log de alteração de conhecimento
    LocalDB.addAuditLog({
      actor: "Usuário Desenvolvedor",
      module: "SecondBrain",
      action: "Edição e Vetorização de Nota",
      details: `Nota "${updatedNote.title}" salva no banco e indexada no ChromaDB. Tags: ${parsedTags.join(", ")}`,
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast(`Nota "${editTitle}" salva no BD e vetorizada no ChromaDB!`, "success");
  };

  // Criar nova nota
  const handleCreateNote = () => {
    const newNote: Note = {
      id: `note-${Date.now()}`,
      title: "Nova Nota de Conhecimento",
      content: "Digite seu conhecimento aqui... Use [[Nome da Nota]] para conectar conceitos.",
      tags: ["#novo", "#sicoobito"],
      links: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    const updated = [newNote, ...notes];
    setNotes(updated);
    selectNote(newNote);
    LocalDB.saveNotes(updated);

    // ✅ INTEGRAÇÃO CHROMADB & AUDITORIA
    ChromaClient.addNoteToChroma(newNote.id, newNote.title, newNote.content);
    LocalDB.addAuditLog({
      actor: "Usuário Desenvolvedor",
      module: "SecondBrain",
      action: "Criação de Nota",
      details: `Nova nota "${newNote.title}" criada e adicionada ao grafo de conexões.`,
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast("Nova nota criada e sincronizada com ChromaDB!", "info");
  };

  // Excluir nota
  const handleDeleteNote = (id: string) => {
    const noteToDelete = notes.find((n) => n.id === id);
    const updated = notes.filter((n) => n.id !== id);
    setNotes(updated);
    LocalDB.saveNotes(updated);
    if (updated.length > 0) {
      selectNote(updated[0]);
    } else {
      setSelectedNote(null);
    }

    // ✅ INTEGRAÇÃO AUDITORIA
    LocalDB.addAuditLog({
      actor: "Usuário Desenvolvedor",
      module: "SecondBrain",
      action: "Exclusão de Nota",
      details: `Nota "${noteToDelete?.title || id}" removida do banco de dados.`,
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast("Nota removida do banco.", "info");
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

    // Calcular posições dos nós em círculo com forças visuais
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

    // 1. Desenhar Arestas (Conexões)
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

    // 2. Desenhar Nós
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

      // Título do nó
      ctx.fillStyle = "#e2e8f0";
      ctx.font = isSelected ? "bold 12px sans-serif" : "11px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(note.title, pos.x, pos.y + 28);
    });
  }, [notes, selectedNote]);

  // Filtragem de notas
  const filteredNotes = notes.filter((n) => {
    const matchesSearch =
      n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.content.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesTag = selectedTagFilter ? n.tags.includes(selectedTagFilter) : true;
    return matchesSearch && matchesTag;
  });

  // Todas as tags únicas
  const allTags = Array.from(new Set(notes.flatMap((n) => n.tags)));

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">📓 Gestão de Conhecimento Estilo Obsidian</span>
          <h1>Segundo Cérebro & Grafo de Notas</h1>
          <p>Conecte pensamentos, documentações técnicas, [[wikilinks]] e tags com persistência no banco de dados.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn-primary glow-button" onClick={handleCreateNote}>
            + Nova Nota
          </button>
        </div>
      </div>

      <div className="obsidian-layout">
        {/* Sidebar de Busca e Lista de Notas */}
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

          {/* Filtros de Tags */}
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
                onKeyDown={(e) => e.key === "Enter" && setSelectedTagFilter(selectedTagFilter === tag ? null : tag)}
              >
                {tag}
              </span>
            ))}
          </div>

          <div className="notes-list">
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
                    <span key={t} className="mini-tag">{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Painel Central: Editor & Visualização de Grafo */}
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
                  <button type="button" className="btn-primary" onClick={handleSaveNote}>
                    💾 Salvar no BD
                  </button>
                  <button type="button" className="btn-danger-sm" onClick={() => handleDeleteNote(selectedNote.id)}>
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
                              <li key={linkId} onClick={() => selectNote(targetNote)} className="clickable-link">
                                🔗 [[{targetNote.title}]]
                              </li>
                            ) : null;
                          })}
                        </ul>
                      ) : (
                        <p className="text-muted text-sm">Nenhum [[wikilink]] vinculado no momento.</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="no-note-selected">Selecione ou crie uma nota no menu lateral</div>
          )}

          {/* Grafo de Nós em Canvas 2D */}
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
