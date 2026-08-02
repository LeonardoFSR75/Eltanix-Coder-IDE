"use client";

import React, { useEffect, useRef, useState } from "react";
import { LocalDB, PDFDocument } from "@/lib/db";
import { ChromaClient, ChromaVectorChunk, ChromaCollection } from "@/lib/chroma";
import { useToast } from "@/components/Toast";

export default function RAGPage() {
  const { addToast } = useToast();
  const vectorCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const [pdfs, setPdfs] = useState<PDFDocument[]>([]);
  const [collections, setCollections] = useState<ChromaCollection[]>([]);
  const [vectors, setVectors] = useState<ChromaVectorChunk[]>([]);

  // Form para upload simulado de PDF
  const [pdfName, setPdfName] = useState("");
  const [pdfText, setPdfText] = useState("");
  const [chunkSize, setChunkSize] = useState(512);

  // RAG Search & Chat
  const [searchQuery, setSearchQuery] = useState("Como o ChromaDB e o MCP funcionam no SicoobitoCode?");
  const [searchResults, setSearchResults] = useState<ChromaVectorChunk[]>([]);
  const [chatMessages, setChatMessages] = useState<
    { sender: "user" | "rag"; text: string; citations?: string[] }[]
  >([
    {
      sender: "rag",
      text: "Olá! Eu sou o assistente RAG do SicoobitoCode. Faça perguntas sobre os PDFs salvos ou cole um novo documento para indexar no ChromaDB.",
    },
  ]);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    setPdfs(LocalDB.getPDFs());
    setCollections(ChromaClient.getCollections());
    setVectors(ChromaClient.getVectors());
  }, []);

  // Executa busca semântica no ChromaDB
  const handlePerformSearch = () => {
    if (!searchQuery.trim()) return;
    setIsSearching(true);

    setTimeout(() => {
      const results = ChromaClient.querySimilarity(searchQuery, 3);
      setSearchResults(results);
      setIsSearching(false);
      addToast(`Recuperados ${results.length} trechos relevantes do ChromaDB!`, "success");
    }, 400);
  };

  // Enviar mensagem no RAG Chat Playground
  const handleSendChatMessage = () => {
    if (!searchQuery.trim()) return;

    const userMsg = searchQuery;
    const newChat = [...chatMessages, { sender: "user" as const, text: userMsg }];
    setChatMessages(newChat);
    setIsSearching(true);

    setTimeout(() => {
      const chunks = ChromaClient.querySimilarity(userMsg, 3);
      setSearchResults(chunks);

      const citations = chunks.map(
        (c) => `[Doc: ${c.filename} - Pág ${c.metadata.pageNumber}]`
      );

      const ragResponse = `Com base nas informações indexadas no ChromaDB:\n\n${chunks[0]?.text || "Informação encontrada na base de conhecimento."}\n\nO sistema garante baixa latência e total privacidade operando 100% localmente.`;

      setChatMessages([
        ...newChat,
        {
          sender: "rag",
          text: ragResponse,
          citations,
        },
      ]);
      setIsSearching(false);
    }, 600);
  };

  // Upload e Indexação de novo PDF
  const handleUploadPDF = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pdfName || !pdfText) return;

    const newPdf: PDFDocument = {
      id: `pdf-${Date.now()}`,
      filename: pdfName.endsWith(".pdf") ? pdfName : `${pdfName}.pdf`,
      sizeBytes: Math.floor(pdfText.length * 1.5 + 50000),
      uploadedAt: new Date().toISOString(),
      pageCount: Math.ceil(pdfText.length / 500) || 1,
      chunkCount: Math.ceil(pdfText.length / chunkSize) || 1,
      chromaCollection: "documentos_usuario",
      rawText: pdfText,
    };

    const updatedPdfs = [newPdf, ...pdfs];
    setPdfs(updatedPdfs);
    LocalDB.savePDFs(updatedPdfs);

    // Indexar vetores no ChromaDB
    const updatedVectors = ChromaClient.addPDFToChroma(newPdf.id, newPdf.filename, pdfText, chunkSize);
    setVectors(updatedVectors);

    // ✅ INTEGRAÇÃO AUDITORIA: Registro de Log automático
    LocalDB.addAuditLog({
      actor: "Usuário Engenheiro de IA",
      module: "RAG",
      action: "Upload e Indexação de PDF",
      details: `Arquivo ${newPdf.filename} indexado com ${newPdf.chunkCount} chunks no ChromaDB e salvo no bucket S3 (MinIO).`,
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    setPdfName("");
    setPdfText("");
    addToast(`PDF "${newPdf.filename}" indexado no ChromaDB e armazenado no MinIO S3!`, "success");
  };

  // Desenhar Projeção 2D de Embeddings do ChromaDB no Canvas
  useEffect(() => {
    const canvas = vectorCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Eixos X e Y centrais
    ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(width / 2, 0);
    ctx.lineTo(width / 2, height);
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
    ctx.stroke();

    // Desenhar pontos de vetores
    vectors.forEach((v) => {
      const [x, y] = v.embedding; // Coordenadas -1 a 1
      const cx = (x + 1) * (width / 2);
      const cy = (-y + 1) * (height / 2);

      const isMatch = searchResults.some((sr) => sr.id === v.id);

      ctx.beginPath();
      ctx.arc(cx, cy, isMatch ? 10 : 6, 0, Math.PI * 2);
      ctx.fillStyle = isMatch ? "#ef4444" : "#3b82f6";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = isMatch ? 2 : 1;
      ctx.stroke();

      // Rótulo do documento
      ctx.fillStyle = isMatch ? "#fca5a5" : "#94a3b8";
      ctx.font = "10px sans-serif";
      ctx.fillText(v.filename.slice(0, 14), cx + 10, cy + 4);
    });
  }, [vectors, searchResults]);

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">📚 Laboratório RAG & ChromaDB</span>
          <h1>Recuperação Vetorial & Gestão de PDFs</h1>
          <p>Fatiamento de documentos, busca por similaridade de cosseno e chat sintético com citação de fontes.</p>
        </div>
        <div className="header-actions">
          <span className="badge-tag blue">ChromaDB Online</span>
          <span className="badge-tag green">Embedding: text-embedding-3-small</span>
        </div>
      </div>

      <div className="grid grid-3-1">
        {/* Projeção 2D de Vetores e Resultados da Busca */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Projeção 2D do Espaço Vetorial no ChromaDB</h3>
            <span className="text-xs text-muted">{vectors.length} Chunks de Embeddings</span>
          </div>

          <div className="canvas-wrapper">
            <canvas ref={vectorCanvasRef} width={750} height={260} className="vector-canvas" />
          </div>

          {/* Tester de Busca Semântica */}
          <div className="rag-search-bar">
            <input
              type="text"
              className="input-text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Digite sua dúvida técnica para buscar no ChromaDB..."
            />
            <button
              type="button"
              className="btn-primary glow-button"
              onClick={handlePerformSearch}
              disabled={isSearching}
            >
              {isSearching ? "Buscando..." : "🔍 Testar Busca Vetorial"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={handleSendChatMessage}
              disabled={isSearching}
            >
              💬 Perguntar no Chat
            </button>
          </div>

          {/* Trechos Recuperados (Top-K Chunks) */}
          {searchResults.length > 0 && (
            <div className="retrieved-chunks-list">
              <h4>🎯 Top-{searchResults.length} Trechos Mais Semelhantes (Cos Similarity)</h4>
              <div className="grid grid-3">
                {searchResults.map((res) => (
                  <div key={res.id} className="chunk-card">
                    <div className="chunk-card-header">
                      <span className="badge-tag green">
                        Score: {((res.similarityScore || 0) * 100).toFixed(1)}%
                      </span>
                      <span className="text-xs text-muted">Pág {res.metadata.pageNumber}</span>
                    </div>
                    <div className="chunk-filename">{res.filename}</div>
                    <p className="chunk-text">"{res.text}"</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Upload & Indexação de PDFs */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>+ Ingerir Novo PDF / Documento</h3>
          </div>

          <form onSubmit={handleUploadPDF} className="config-form">
            <div className="form-group">
              <label htmlFor="pdf-title">Nome do Documento PDF</label>
              <input
                id="pdf-title"
                type="text"
                className="input-text"
                value={pdfName}
                onChange={(e) => setPdfName(e.target.value)}
                placeholder="Ex: Manual_Sicoobito_2026.pdf"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="pdf-content">Texto Bruto / Conteúdo Extraído do PDF</label>
              <textarea
                id="pdf-content"
                value={pdfText}
                onChange={(e) => setPdfText(e.target.value)}
                className="input-textarea"
                rows={5}
                placeholder="Cole aqui o texto do PDF para ser fatiado e indexado no ChromaDB..."
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="chunk-size-slider">Tamanho do Fatia (Chunk Size): {chunkSize} tokens</label>
              <input
                id="chunk-size-slider"
                type="range"
                min="128"
                max="1024"
                step="64"
                value={chunkSize}
                onChange={(e) => setChunkSize(parseInt(e.target.value, 10))}
                className="range-input"
              />
            </div>

            <button type="submit" className="btn-primary btn-block">
              💾 Indexar no ChromaDB & Salvar no BD
            </button>
          </form>
        </div>
      </div>

      {/* RAG Chat Playground & Biblioteca de PDFs Salvos */}
      <div className="grid grid-2">
        {/* Chat Playground RAG */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>💬 Playground de Chat RAG com Citações</h3>
          </div>

          <div className="chat-messages-container">
            {chatMessages.map((msg, idx) => (
              <div key={idx} className={`chat-bubble ${msg.sender}`}>
                <div className="chat-sender-name">
                  {msg.sender === "user" ? "👤 Você" : "🤖 Assistente RAG (ChromaDB)"}
                </div>
                <div className="chat-text whitespace-pre-wrap">{msg.text}</div>
                {msg.citations && msg.citations.length > 0 && (
                  <div className="chat-citations">
                    {msg.citations.map((c, i) => (
                      <span key={i} className="citation-tag">{c}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Lista de PDFs Persistidos */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>📄 Documentos PDF Armazenados no BD</h3>
            <span className="badge-tag blue">{pdfs.length} PDFs</span>
          </div>

          <div className="pdf-documents-list">
            {pdfs.map((p) => (
              <div key={p.id} className="pdf-item-card">
                <div className="pdf-icon">📕</div>
                <div className="pdf-info">
                  <div className="pdf-name">{p.filename}</div>
                  <div className="pdf-meta">
                    {p.pageCount} páginas · {p.chunkCount} chunks no ChromaDB · {(p.sizeBytes / 1024 / 1024).toFixed(2)} MB
                  </div>
                </div>
                <span className="badge-tag green">Indexado</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
