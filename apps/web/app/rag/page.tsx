"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { ingestWeb } from "@/lib/api/firecrawl";

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

function getDocIcon(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.startsWith("[web]")) return "🌐";
  if (lower.endsWith(".pdf")) return "📕";
  if (
    lower.endsWith(".docx") ||
    lower.endsWith(".doc") ||
    lower.endsWith(".docm") ||
    lower.endsWith(".odt")
  )
    return "📘";
  if (
    lower.endsWith(".xlsx") ||
    lower.endsWith(".xls") ||
    lower.endsWith(".ods") ||
    lower.endsWith(".csv") ||
    lower.endsWith(".tsv")
  )
    return "📊";
  if (lower.endsWith(".pptx") || lower.endsWith(".ppt") || lower.endsWith(".odp")) return "📙";
  if (lower.endsWith(".epub") || lower.endsWith(".rtf")) return "📗";
  if (lower.endsWith(".md") || lower.endsWith(".txt")) return "📄";
  return "📑";
}

export default function RAGPage() {
  const { addToast } = useToast();
  const router = useRouter();
  const { currentProject } = useProject();

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [uploading, setUploading] = useState(false);

  // Web Import (Firecrawl)
  const [webUrl, setWebUrl] = useState("");
  const [isCrawl, setIsCrawl] = useState(false);
  const [crawlMaxDepth, setCrawlMaxDepth] = useState(2);
  const [crawlLimit, setCrawlLimit] = useState(10);
  const [importingWeb, setImportingWeb] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<DocumentSearchHit[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // Guarda contra resposta fora de ordem: sem isso, trocar de projeto duas
  // vezes rápido pode fazer a resposta do projeto antigo chegar depois da do
  // novo e sobrescrever a lista com documentos do projeto errado.
  const requestIdRef = useRef(0);

  const refreshDocuments = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    try {
      const docs = await listDocuments(currentProject);
      if (requestIdRef.current !== requestId) return;
      setDocuments(docs);
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      addToast(err instanceof Error ? err.message : "Falha ao listar documentos.", "error");
    } finally {
      if (requestIdRef.current === requestId) setLoadingDocs(false);
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

  const handleWebImport = async (e: React.FormEvent) => {
    e.preventDefault();
    const url = webUrl.trim();
    if (!url) return;
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      addToast("A URL deve começar com http:// ou https://", "error");
      return;
    }
    setImportingWeb(true);
    try {
      const resp = await ingestWeb({
        url,
        project: currentProject,
        crawl: isCrawl,
        maxDepth: crawlMaxDepth,
        limit: crawlLimit,
      });
      if (isCrawl) {
        addToast(
          `Crawl concluído: ${resp.result.pages_indexed ?? 0} página(s) e ${resp.result.total_chunks ?? 0} chunks indexados.`,
          "success",
        );
      } else {
        addToast(
          `"${resp.result.filename || url}" indexado com sucesso (${resp.result.chunk_count ?? 0} chunks).`,
          "success",
        );
      }
      setWebUrl("");
      await refreshDocuments();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao importar da web via Firecrawl.", "error");
    } finally {
      setImportingWeb(false);
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
            <h3>+ Enviar Documento</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="pdf-upload">Arquivo (PDF, Word, Excel, PPT, ODF, CSV, EPUB, RTF)</label>
              <input
                id="pdf-upload"
                type="file"
                accept=".pdf,.docx,.doc,.docm,.xlsx,.xls,.xlsm,.xlsb,.pptx,.ppt,.ppsx,.odt,.ods,.odp,.rtf,.epub,.csv,.tsv,.txt,.md"
                onChange={handleFileChange}
                disabled={uploading}
              />
            </div>
            {uploading && <p className="text-xs text-muted">Enviando e agendando indexação…</p>}
          </div>

          <div className="panel-header" style={{ marginTop: 20, borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
            <h3>🔥 Importar da Web (Firecrawl)</h3>
          </div>

          <form onSubmit={handleWebImport} className="config-form">
            <div className="form-group">
              <label htmlFor="web-url">URL da Página ou Documentação</label>
              <input
                id="web-url"
                type="url"
                className="input-text"
                placeholder="https://docs.exemplo.com"
                value={webUrl}
                onChange={(e) => setWebUrl(e.target.value)}
                disabled={importingWeb}
                required
              />
            </div>

            <div className="form-group" style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
              <input
                id="crawl-checkbox"
                type="checkbox"
                checked={isCrawl}
                onChange={(e) => setIsCrawl(e.target.checked)}
                disabled={importingWeb}
              />
              <label htmlFor="crawl-checkbox" style={{ margin: 0, cursor: "pointer", fontSize: 13 }}>
                Rastrear documentação completa (Crawl)
              </label>
            </div>

            {isCrawl && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 8 }}>
                <div className="form-group">
                  <label htmlFor="crawl-depth" style={{ fontSize: 12 }}>Profundidade</label>
                  <input
                    id="crawl-depth"
                    type="number"
                    min={1}
                    max={4}
                    className="input-text"
                    value={crawlMaxDepth}
                    onChange={(e) => setCrawlMaxDepth(Number(e.target.value))}
                    disabled={importingWeb}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="crawl-limit" style={{ fontSize: 12 }}>Limite págs</label>
                  <input
                    id="crawl-limit"
                    type="number"
                    min={1}
                    max={30}
                    className="input-text"
                    value={crawlLimit}
                    onChange={(e) => setCrawlLimit(Number(e.target.value))}
                    disabled={importingWeb}
                  />
                </div>
              </div>
            )}

            <button
              type="submit"
              className="btn-primary glow-button"
              style={{ width: "100%", marginTop: 8 }}
              disabled={importingWeb || !webUrl.trim()}
            >
              {importingWeb ? (isCrawl ? "Rastreando e Indexando…" : "Raspando e Indexando…") : (isCrawl ? "🚀 Rastrear & Indexar" : "⚡ Raspar & Indexar")}
            </button>
            {importingWeb && <p className="text-xs text-muted" style={{ marginTop: 6 }}>Processando via Firecrawl e gerando vetores…</p>}
          </form>
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
              <div className="pdf-icon">{getDocIcon(doc.filename)}</div>
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
