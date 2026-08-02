"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { LocalDB, Note, PDFDocument, Skill, MCPServer, AuditLog, NeuralModel } from "@/lib/db";
import { ChromaClient, ChromaVectorChunk } from "@/lib/chroma";

export default function HomePage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [pdfs, setPdfs] = useState<PDFDocument[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [neuralModels, setNeuralModels] = useState<NeuralModel[]>([]);
  const [vectors, setVectors] = useState<ChromaVectorChunk[]>([]);

  useEffect(() => {
    setNotes(LocalDB.getNotes());
    setPdfs(LocalDB.getPDFs());
    setSkills(LocalDB.getSkills());
    setMcpServers(LocalDB.getMCP());
    setAuditLogs(LocalDB.getAudit());
    setNeuralModels(LocalDB.getNeuralModels());
    setVectors(ChromaClient.getVectors());
  }, []);

  const totalChunks = pdfs.reduce((acc, p) => acc + p.chunkCount, 0);

  return (
    <div className="shell">
      {/* Header Banner */}
      <div className="command-banner">
        <div className="banner-content">
          <div className="banner-badge">🚀 Central de Operações do Sistema</div>
          <h1>Painel Principal SicoobitoCode</h1>
          <p>
            Plataforma local-first integrando <strong>IDE Agêntica</strong>, <strong>Provedores de LLM</strong>, <strong>Contabilidade de Custo</strong>, <strong>ChromaDB</strong>, <strong>Segundo Cérebro</strong>, <strong>Redes Neurais</strong>, <strong>Skills</strong>, <strong>MCP</strong> e <strong>Auditoria</strong>.
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
          <div className="stat-value">{vectors.length + totalChunks}</div>
          <div className="stat-label">Vetores no ChromaDB</div>
          <div className="stat-hint">{pdfs.length} documentos PDF no BD</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">📓</span>
          <div className="stat-value">{notes.length}</div>
          <div className="stat-label">Notas Segundo Cérebro</div>
          <div className="stat-hint">Grafo de conexões ativo</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">🧠</span>
          <div className="stat-value">{neuralModels.length}</div>
          <div className="stat-label">Redes Neurais</div>
          <div className="stat-hint">Acurácia média 96.5%</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">⚡</span>
          <div className="stat-value">{skills.length}</div>
          <div className="stat-label">Skills Ativas</div>
          <div className="stat-hint">Ferramentas de Agente</div>
        </div>

        <div className="stat-card">
          <span className="stat-icon">🔌</span>
          <div className="stat-value">{mcpServers.length}</div>
          <div className="stat-label">Servidores MCP</div>
          <div className="stat-hint">STDIO / SSE Online</div>
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
          <Link href="/neural-network" className="module-card">
            <div className="module-header">
              <span className="module-icon">🧠</span>
              <span className="module-badge">Simulador 2D</span>
            </div>
            <h3>Rede Neural Interativa</h3>
            <p>
              Projeta camadas ocultas, ajusta funções de ativação (ReLU, Tanh, Sigmoid) e visualiza a curva de perda (*loss*) em tempo real.
            </p>
            <div className="module-footer">
              <span>{neuralModels.length} modelos salvos</span>
              <span className="arrow-link">Explorar →</span>
            </div>
          </Link>

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
              <span>{pdfs.length} PDFs armazenados</span>
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
              <span className="module-badge">JSON-RPC 2.0</span>
            </div>
            <h3>Gestão MCP (Model Context)</h3>
            <p>
              Monitore servidores de contexto MCP, inspecione chamadas de ferramentas e execute requisições via console.
            </p>
            <div className="module-footer">
              <span>{mcpServers.length} servidores ativos</span>
              <span className="arrow-link">Explorar →</span>
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
              <span>ChromaDB Vector Store</span>
              <strong>3 Coleções / {vectors.length + totalChunks} Chunks</strong>
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
            {auditLogs.slice(0, 4).map((log) => (
              <div key={log.id} className="feed-item">
                <span className={`risk-dot ${log.riskLevel}`} />
                <div className="feed-details">
                  <div className="feed-title">{log.action}</div>
                  <div className="feed-meta">
                    {log.actor} · {log.module} · {new Date(log.timestamp).toLocaleTimeString("pt-BR")}
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
