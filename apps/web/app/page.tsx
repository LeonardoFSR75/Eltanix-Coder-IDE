"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { DocumentSummary, listDocuments } from "@/lib/api/documents";
import { NoteRecord, listNotes } from "@/lib/api/notes";
import { SkillRecord, listSkills } from "@/lib/api/skills";
import { AuditEntry, listAudit } from "@/lib/api/audit";
import { MCPServerRecord, listMcpServers } from "@/lib/api/mcp";

export default function HomePage() {
  const [notes, setNotes] = useState<NoteRecord[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [mcpServers, setMcpServers] = useState<MCPServerRecord[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([]);

  useEffect(() => {
    listNotes().then(setNotes).catch(() => setNotes([]));
    listDocuments().then(setDocuments).catch(() => setDocuments([]));
    listSkills().then(setSkills).catch(() => setSkills([]));
    listAudit().then(setAuditLogs).catch(() => setAuditLogs([]));
    listMcpServers().then(setMcpServers).catch(() => setMcpServers([]));
  }, []);

  const totalChunks = documents.reduce((acc, d) => acc + d.chunk_count, 0);

  return (
    <div className="shell">
      {/* Header Banner */}
      <div className="command-banner">
        <div className="banner-content">
          <div className="banner-badge">🚀 Central de Operações do Sistema</div>
          <h1>Painel Principal SicoobitoCode</h1>
          <p>
            Plataforma local-first integrando <strong>IDE Agêntica</strong>, <strong>Provedores de LLM</strong>, <strong>Contabilidade de Custo</strong>, <strong>RAG</strong>, <strong>Segundo Cérebro</strong>, <strong>Skills</strong>, <strong>MCP</strong> e <strong>Auditoria</strong>.
          </p>
        </div>
        <div className="banner-actions">
          <Link href="/ide" className="btn-primary glow-button">
            💻 Abrir IDE Agêntica
          </Link>
          <Link href="/rag" className="btn-secondary">
            📚 Consultar RAG & ChromaDB
          </Link>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-6">
        <div className="stat-card">
          <span className="stat-icon">💻</span>
          <div className="stat-value">IDE</div>
          <div className="stat-label">Ambiente Agêntico</div>
          <div className="stat-hint">Editor Monaco + Pyright</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">📚</span>
          <div className="stat-value">{totalChunks}</div>
          <div className="stat-label">Chunks indexados (pgvector)</div>
          <div className="stat-hint">{documents.length} documentos no RAG</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">📓</span>
          <div className="stat-value">{notes.length}</div>
          <div className="stat-label">Notas Segundo Cérebro</div>
          <div className="stat-hint">Grafo de conexões ativo</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">⚡</span>
          <div className="stat-value">{skills.length}</div>
          <div className="stat-label">Skills Ativas</div>
          <div className="stat-hint">Ferramentas de Agente</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">🔌</span>
          <div className="stat-value">
            {mcpServers.filter((s) => s.status === "connected").length}/{mcpServers.length}
          </div>
          <div className="stat-label">Servidores MCP</div>
          <div className="stat-hint">Conectados / Cadastrados</div>
        </div>
      </div>

      {/* Quick Access Modules Grid */}
      <section className="section-block">
        <h2 className="section-title">
          <span>🛠️ Ferramentas & Subsistemas do Ecossistema</span>
          <span className="section-subtitle">Acesso direto ao editor de código, ferramentas de custo e IA</span>
        </h2>

        <div className="grid grid-3">
          {/* Ferramentas Originais */}
          <Link href="/ide" className="module-card">
            <div className="module-header">
              <span className="module-icon">💻</span>
              <span className="module-badge font-mono">IDE Local</span>
            </div>
            <h3>IDE Agêntica & Editor Monaco</h3>
            <p>
              Ambiente de desenvolvimento completo com suporte a Pyright LSP, terminal integrado, execução de agentes e árvore de arquivos.
            </p>
            <div className="module-footer">
              <span>Monaco Editor + Terminal</span>
              <span className="arrow-link">Abrir IDE →</span>
            </div>
          </Link>

          <Link href="/providers" className="module-card">
            <div className="module-header">
              <span className="module-icon">🌐</span>
              <span className="module-badge font-mono">Gateway</span>
            </div>
            <h3>Provedores de LLM & Chaves</h3>
            <p>
              Gerencie conexões de API para OpenAI, Anthropic, Gemini, Ollama local e roteamento multi-modelo com fallback automático.
            </p>
            <div className="module-footer">
              <span>Configuração de Modelos</span>
              <span className="arrow-link">Gerenciar →</span>
            </div>
          </Link>

          <Link href="/requests" className="module-card">
            <div className="module-header">
              <span className="module-icon">📊</span>
              <span className="module-badge font-mono">Métricas</span>
            </div>
            <h3>Requests, Custo & Economia</h3>
            <p>
              Histórico detalhado de consumo de tokens, contabilidade de custo em USD, cache exato e estatísticas de economia.
            </p>
            <div className="module-footer">
              <span>Logs & FinOps de IA</span>
              <span className="arrow-link">Visualizar →</span>
            </div>
          </Link>

          {/* Novas Ferramentas */}
          <Link href="/second-brain" className="module-card">
            <div className="module-header">
              <span className="module-icon">📓</span>
              <span className="module-badge">Obsidian Style</span>
            </div>
            <h3>Segundo Cérebro & Grafo</h3>
            <p>
              Gestão de conhecimento com mapa de conexões interativo, editor Markdown com suporte a <code>[[wikilinks]]</code> e tags.
            </p>
            <div className="module-footer">
              <span>{notes.length} notas no BD</span>
              <span className="arrow-link">Explorar →</span>
            </div>
          </Link>

          <Link href="/rag" className="module-card">
            <div className="module-header">
              <span className="module-icon">📚</span>
              <span className="module-badge">ChromaDB + PDFs</span>
            </div>
            <h3>RAG & Busca Vetorial</h3>
            <p>
              Upload de documentos PDF, extração de texto, fatiamento (*chunking*), visualizador de embeddings e chat com citação.
            </p>
            <div className="module-footer">
              <span>{documents.length} documentos armazenados</span>
              <span className="arrow-link">Explorar →</span>
            </div>
          </Link>

          <Link href="/skills" className="module-card">
            <div className="module-header">
              <span className="module-icon">⚡</span>
              <span className="module-badge">Sandbox</span>
            </div>
            <h3>Biblioteca de Skills</h3>
            <p>
              Cadastre prompts de sistema, parâmetros de ferramentas e execute simulações em ambiente sandbox seguro.
            </p>
            <div className="module-footer">
              <span>{skills.length} skills configuradas</span>
              <span className="arrow-link">Explorar →</span>
            </div>
          </Link>

          <Link href="/mcp" className="module-card">
            <div className="module-header">
              <span className="module-icon">🔌</span>
              <span className="module-badge">Model Context Protocol</span>
            </div>
            <h3>Conectores MCP do Agente</h3>
            <p>
              Conecte servidores MCP (stdio ou Streamable HTTP) — cada um vira ferramentas reais
              que o agente pode chamar, com aprovação para ações de escrita.
            </p>
            <div className="module-footer">
              <span>{mcpServers.length} servidor(es) cadastrado(s)</span>
              <span className="arrow-link">Gerenciar →</span>
            </div>
          </Link>

          <Link href="/audit" className="module-card">
            <div className="module-header">
              <span className="module-icon">🛡️</span>
              <span className="module-badge">Governança</span>
            </div>
            <h3>Logs de Auditoria</h3>
            <p>
              Acompanhe tentativas de acesso, detecção de injeção de prompt e alterações de sistema salvas no banco de dados.
            </p>
            <div className="module-footer">
              <span>{auditLogs.length} logs registrados</span>
              <span className="arrow-link">Explorar →</span>
            </div>
          </Link>
        </div>
      </section>

      {/* Database & Status Section */}
      <div className="grid grid-2">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🗄️ Status da Infraestrutura & Banco</h3>
            <span className="badge-tag green">Conectado</span>
          </div>
          <div className="db-stats-list">
            <div className="db-stat-item">
              <span>IDE Agêntica & Pyright LSP</span>
              <strong>Ativo (Porta 5400 / Docker)</strong>
            </div>
            <div className="db-stat-item">
              <span>Banco Relacional (Postgres 17 + pgvector)</span>
              <strong>Ativo no Docker (Porta 5403)</strong>
            </div>
            <div className="db-stat-item">
              <span>Índice pgvector (Documentos + Código)</span>
              <strong>{totalChunks} Chunks</strong>
            </div>
            <div className="db-stat-item">
              <span>Redis Cache & Cache Exato</span>
              <strong>Ativo no Docker (Porta 5404)</strong>
            </div>
          </div>
        </div>

        <div className="panel-box">
          <div className="panel-header">
            <h3>⚡ Atividades Recentes do Sistema</h3>
            <Link href="/audit" className="text-link-sm">Ver todos →</Link>
          </div>
          <div className="activity-feed">
            {auditLogs.length === 0 && (
              <p className="text-xs text-muted">Nenhuma atividade registrada ainda.</p>
            )}
            {auditLogs.slice(0, 4).map((log) => (
              <div key={log.id} className="feed-item">
                <span className={`risk-dot ${log.risk_level}`} />
                <div className="feed-details">
                  <div className="feed-title">{log.action}</div>
                  <div className="feed-meta">
                    {log.actor} · {log.module} ·{" "}
                    {new Date(log.created_at).toLocaleTimeString("pt-BR")}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
