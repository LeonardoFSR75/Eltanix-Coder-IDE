"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import { useProject } from "@/components/providers/ProjectContext";
import {
  DocumentSearchHit,
  DocumentSummary,
  confirmUpload,
  deleteDocument,
  listDocuments,
  requestUploadUrl,
  searchDocuments,
  uploadToPresignedUrl,
} from "@/lib/api/documents";

const POLL_INTERVAL_MS = 2000;

const STATUS_LABEL: Record<DocumentSummary["status"], string> = {
  pending: "Aguardando upload",
  processing: "Indexando…",
  ready: "Indexado",
  failed: "Falhou",
};

const STATUS_COLOR: Record<DocumentSummary["status"], string> = {
  pending: "blue",
  processing: "blue",
  ready: "green",
  failed: "red",
};

export default function RAGPage() {
  const { addToast } = useToast();
  const router = useRouter();
  const { currentProject } = useProject();

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [uploading, setUploading] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<DocumentSearchHit[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const refreshDocuments = useCallback(async () => {
    try {
      setDocuments(await listDocuments(currentProject));
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao listar documentos.", "error");
    } finally {
      setLoadingDocs(false);
    }
  }, [addToast, currentProject]);

  useEffect(() => {
    refreshDocuments();
  }, [refreshDocuments]);

  // Enquanto algum documento está pending/processing, reconsulta a lista até
  // tudo assentar em ready/failed — a ingestão roda em segundo plano no backend.
  useEffect(() => {
    const hasPending = documents.some(
      (d) => d.status === "pending" || d.status === "processing",
    );
    if (!hasPending) return;
    const timer = setInterval(refreshDocuments, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [documents, refreshDocuments]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.type !== "application/pdf") {
      addToast("Só PDFs são aceitos por enquanto.", "error");
      return;
    }
    setUploading(true);
    try {
      const { document_id, upload_url } = await requestUploadUrl(file, currentProject);
      await uploadToPresignedUrl(upload_url, file);
      await confirmUpload(document_id);
      addToast(`"${file.name}" enviado — indexando em segundo plano.`, "success");
      await refreshDocuments();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha no upload.", "error");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string, filename: string) => {
    try {
      await deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      addToast(`"${filename}" removido.`, "success");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao remover documento.", "error");
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    try {
      const hits = await searchDocuments(searchQuery, 5, currentProject);
      setSearchResults(hits);
      if (hits.length === 0) {
        addToast("Nenhum trecho encontrado.", "info");
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha na busca.", "error");
    } finally {
      setIsSearching(false);
    }
  };

  const askAgent = () => {
    if (!searchQuery.trim()) return;
    router.push(`/ide?agentPrompt=${encodeURIComponent(searchQuery)}`);
  };

  const readyCount = documents.filter((d) => d.status === "ready").length;

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">📚 RAG de Documentos</span>
          <h1>Busca em PDFs para o Agente</h1>
          <p>
            Envie PDFs para o índice híbrido (pgvector + full-text) do backend. O agente do
            IDE já enxerga este material sozinho, via a ferramenta{" "}
            <code className="inline-code">search_documents</code>.
            {currentProject ? (
              <> Filtrado pelo projeto <strong>{currentProject}</strong> (mais os globais).</>
            ) : (
              <> Sem projeto selecionado — mostrando todos os documentos.</>
            )}
          </p>
        </div>
        <div className="header-actions">
          <Link
            href={currentProject ? `/second-brain?project=${encodeURIComponent(currentProject)}` : "/second-brain"}
            className="btn-secondary-sm"
          >
            📓 Segundo Cérebro
          </Link>
          <Link
            href={currentProject ? `/graphify?project=${encodeURIComponent(currentProject)}` : "/graphify"}
            className="btn-secondary-sm"
          >
            🕸️ Graphify Engine
          </Link>
        </div>
      </div>

      <div className="grid grid-3-1">
        <div className="panel-box">
          <div className="panel-header">
            <h3>Testar busca</h3>
            <span className="text-xs text-muted">{readyCount} documento(s) indexado(s)</span>
          </div>

          <div className="rag-search-bar">
            <input
              type="text"
              className="input-text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Digite sua dúvida para buscar nos documentos..."
            />
            <button
              type="button"
              className="btn-primary glow-button"
              onClick={handleSearch}
              disabled={isSearching}
            >
              {isSearching ? "Buscando..." : "🔍 Buscar"}
            </button>
            <button type="button" className="btn-secondary" onClick={askAgent}>
              🤖 Perguntar ao Agente
            </button>
          </div>

          {searchResults.length > 0 && (
            <div className="retrieved-chunks-list">
              <h4>🎯 Top-{searchResults.length} trechos mais relevantes</h4>
              <div className="grid grid-3">
                {searchResults.map((hit) => (
                  <div key={`${hit.document_id}-${hit.chunk_index}`} className="chunk-card">
                    <div className="chunk-card-header">
                      <span className="badge-tag green">Score: {(hit.score * 100).toFixed(2)}%</span>
                      {hit.page_number != null && (
                        <span className="text-xs text-muted">Pág {hit.page_number}</span>
                      )}
                    </div>
                    <div className="chunk-filename">{hit.filename}</div>
                    <p className="chunk-text">&quot;{hit.content}&quot;</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="panel-box">
          <div className="panel-header">
            <h3>+ Enviar PDF</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="pdf-upload">Arquivo PDF</label>
              <input
                id="pdf-upload"
                type="file"
                accept="application/pdf"
                onChange={handleFileChange}
                disabled={uploading}
              />
            </div>
            {uploading && <p className="text-xs text-muted">Enviando e agendando indexação…</p>}
          </div>
        </div>
      </div>

      <div className="panel-box">
        <div className="panel-header">
          <h3>📄 Documentos</h3>
          <span className="badge-tag blue">{documents.length}</span>
        </div>

        <div className="pdf-documents-list">
          {loadingDocs && <p className="text-xs text-muted">Carregando…</p>}
          {!loadingDocs && documents.length === 0 && (
            <p className="text-xs text-muted">Nenhum documento enviado ainda.</p>
          )}
          {documents.map((doc) => (
            <div key={doc.id} className="pdf-item-card">
              <div className="pdf-icon">📕</div>
              <div className="pdf-info">
                <div className="pdf-name">{doc.filename}</div>
                <div className="pdf-meta">
                  {doc.page_count ?? "?"} páginas · {doc.chunk_count} chunks ·{" "}
                  {(doc.size_bytes / 1024).toFixed(0)} KB
                </div>
                {doc.status === "failed" && doc.error && (
                  <div className="text-xs" style={{ color: "var(--danger)" }}>
                    {doc.error}
                  </div>
                )}
              </div>
              <span className={`badge-tag ${STATUS_COLOR[doc.status]}`}>
                {STATUS_LABEL[doc.status]}
              </span>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => handleDelete(doc.id, doc.filename)}
              >
                Remover
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
