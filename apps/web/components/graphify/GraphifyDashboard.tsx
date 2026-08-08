"use client";

import React, { useCallback, useEffect, useState } from "react";
import GraphViewer from "./GraphViewer";
import type { GraphNode, GraphEdge, GraphMetrics } from "@/lib/api/graphify";
import {
  listGraphNodes,
  listGraphEdges,
  getGraphMetrics,
  queryGraph,
  getEgoGraph,
  indexWorkspace,
} from "@/lib/api/graphify";
import { useProject } from "@/components/providers/ProjectContext";

type ViewTab = "universe" | "domain" | "concept" | "architecture" | "brain";

const TABS: { id: ViewTab; label: string }[] = [
  { id: "universe", label: "🌌 Knowledge Universe" },
  { id: "domain", label: "🏢 Domain Graph" },
  { id: "concept", label: "💡 Concept Explorer" },
  { id: "architecture", label: "🏗️ Architecture Graph" },
  { id: "brain", label: "🧠 Second Brain Map" },
];

const TAB_DETAILS: Record<ViewTab, { label: string; description: string; types: string[] }> = {
  universe: {
    label: "🌌 Knowledge Universe",
    description: "Visão global de todas as entidades e conexões do grafo de conhecimento.",
    types: ["Todos os Tipos"],
  },
  domain: {
    label: "🏢 Domain Graph",
    description: "Visão focada na estrutura de domínio (Módulos, Classes e Documentação).",
    types: ["Module", "Class", "Document"],
  },
  concept: {
    label: "💡 Concept Explorer",
    description: "Exploração conceitual de ideias, decisões de arquitetura e notas.",
    types: ["Concept", "Note", "ADR"],
  },
  architecture: {
    label: "🏗️ Architecture Graph",
    description: "Arquitetura de código-fonte: módulos, classes, funções e ADRs.",
    types: ["Module", "Class", "Function", "ADR"],
  },
  brain: {
    label: "🧠 Second Brain Map",
    description: "Conhecimento pessoal do Segundo Cérebro (Notas, Conceitos e destaque para Nós Órfãos).",
    types: ["Note", "Concept", "Author", "Document"],
  },
};

export default function GraphifyDashboard() {
  const { currentProject } = useProject();
  const workspace = currentProject ?? "default";
  const [activeTab, setActiveTab] = useState<ViewTab>("universe");
  const [searchQuery, setSearchQuery] = useState("");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [metrics, setMetrics] = useState<GraphMetrics | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isIndexing, setIsIndexing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState<string | null>(null);

  const fetchGraphData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [nodesData, edgesData, metricsData] = await Promise.all([
        listGraphNodes(workspace, 150),
        listGraphEdges(workspace, 500),
        getGraphMetrics(workspace),
      ]);
      setNodes(nodesData);
      setEdges(edgesData);
      setMetrics(metricsData);
      setAnswerText(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar o Grafo de Conhecimento.");
    } finally {
      setIsLoading(false);
    }
  }, [workspace]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsLoading(true);
    setError(null);
    setAnswerText(null);
    try {
      const data = await queryGraph(searchQuery, workspace, 20);
      setNodes(data.nodes ?? []);
      setEdges(data.edges ?? []);
      setAnswerText(data.answer ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro na busca GraphRAG.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectNode = async (node: GraphNode) => {
    setSelectedNode(node);
    setIsLoading(true);
    try {
      const ego = await getEgoGraph(node.id, workspace, 2);
      setNodes(ego.nodes);
      setEdges(ego.edges);
    } catch {
      // Manter grafo atual se ego falhar
    } finally {
      setIsLoading(false);
    }
  };

  const handleIndex = async () => {
    setIsIndexing(true);
    try {
      await indexWorkspace(workspace);
      await fetchGraphData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao iniciar indexação.");
    } finally {
      setIsIndexing(false);
    }
  };

  useEffect(() => {
    void fetchGraphData();
  }, [fetchGraphData]);

  const isEmpty = !isLoading && nodes.length === 0 && !error;

  return (
    <div className="shell">
      {/* ── Page Header ──────────────────────────────────────────────────────────── */}
      <div className="page-header">
        <div>
          <span className="page-badge">🌐 Grafo de Conhecimento Multidimensional</span>
          <h1>Graphify Engine & GraphRAG</h1>
          <p>
            Extração de AST, ecossistemas de código, comunidades e busca semântica em grafos.
            Workspace atual: <code className="inline-code">{workspace}</code>
            {!currentProject && " (nenhum projeto selecionado)"}.
          </p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            onClick={fetchGraphData}
            disabled={isLoading}
            className="btn-secondary"
            title="Recarregar dados do grafo"
          >
            🔄 Recarregar
          </button>
          <button
            type="button"
            onClick={handleIndex}
            disabled={isIndexing}
            className="btn-primary glow-button"
            title="Indexar workspace no Grafo de Conhecimento"
          >
            {isIndexing ? "⏳ Indexando..." : "⚡ Indexar Workspace"}
          </button>
        </div>
      </div>

      {/* ── Search & Controls Bar ────────────────────────────────────────────────── */}
      <div className="graphify-search-card">
        <form onSubmit={handleSearch} className="graphify-search-form">
          <div className="graphify-search-input-wrap">
            <span className="graphify-search-icon">🔍</span>
            <input
              type="text"
              placeholder="GraphRAG: buscar conceito, módulo, classe, nota..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input-text graphify-search-input"
            />
          </div>
          <button type="submit" disabled={isLoading} className="btn-primary">
            Buscar GraphRAG
          </button>
        </form>
      </div>

      {/* ── Error Banner ────────────────────────────────────────────────────────────── */}
      {error && (
        <div className="banner-notice error" style={{ marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>⚠️ {error}</span>
          <button type="button" onClick={() => setError(null)} className="btn-text-sm">✕</button>
        </div>
      )}

      {/* ── Metrics Cards Grid ──────────────────────────────────────────────────────── */}
      {metrics && (
        <div className="grid">
          <div className="card">
            <div className="label">Nós Mapeados</div>
            <div className="value" style={{ color: "var(--accent)" }}>{metrics.total_nodes}</div>
            <div className="hint">Entidades no Grafo</div>
          </div>

          <div className="card">
            <div className="label">Conexões / Arestas</div>
            <div className="value" style={{ color: "var(--accent-purple)" }}>{metrics.total_edges}</div>
            <div className="hint">Relações entre entidades</div>
          </div>

          <div className="card">
            <div className="label">Nós Órfãos</div>
            <div className="value" style={{ color: "var(--warn)" }}>
              {metrics.orphan_nodes_count} <span style={{ fontSize: "14px", fontWeight: "normal", color: "var(--text-muted)" }}>({metrics.orphan_percentage}%)</span>
            </div>
            <div className="hint">Sem conexões com outros nós</div>
          </div>

          <div className="card">
            <div className="label">Densidade do Grafo</div>
            <div className="value" style={{ color: "var(--accent-emerald)" }}>{metrics.density}</div>
            <div className="hint">Grau de conectividade global</div>
          </div>
        </div>
      )}

      {/* ── GraphRAG Answer Banner ──────────────────────────────────────────────────── */}
      {answerText && (
        <div className="graphify-answer-card">
          <span style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--accent)", display: "block", marginBottom: "8px" }}>
            🤖 Resposta GraphRAG
          </span>
          <p style={{ fontSize: "13.5px", color: "var(--text)", lineHeight: 1.6, margin: 0 }}>
            {answerText}
          </p>
        </div>
      )}

      {/* ── Tabs Bar ─────────────────────────────────────────────────────────────── */}
      <div className="graphify-tabs-bar">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`graphify-tab-btn ${activeTab === tab.id ? "active" : ""}`}
          >
            {tab.label}
          </button>
        ))}
        {selectedNode && (
          <button
            type="button"
            onClick={() => { setSelectedNode(null); void fetchGraphData(); }}
            className="btn-secondary"
            style={{ marginLeft: "auto", fontSize: "12px", padding: "6px 12px" }}
          >
            ← Voltar ao Grafo Completo
          </button>
        )}
      </div>

      {/* ── Active Tab Details Banner ─────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: "12.5px",
          color: "var(--text-dim)",
          marginBottom: "16px",
          background: "var(--surface-glass)",
          padding: "10px 16px",
          borderRadius: "var(--radius)",
          border: "1px solid var(--border)",
          flexWrap: "wrap",
          gap: "10px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <strong style={{ color: "var(--accent)" }}>{TAB_DETAILS[activeTab].label}:</strong>
          <span>{TAB_DETAILS[activeTab].description}</span>
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Entidades exibidas:</span>
          {TAB_DETAILS[activeTab].types.map((t) => (
            <span
              key={t}
              className="graphify-badge"
              style={{
                backgroundColor: "var(--surface-2)",
                color: "var(--accent-purple)",
                border: "1px solid var(--border)",
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* ── Main Graph Viewer ─────────────────────────────────────────────────────── */}
      {isLoading ? (
        <div className="graphify-viewer-card" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "16px", height: "550px" }}>
          <div className="loading-spinner" style={{ width: "36px", height: "36px", border: "3px solid var(--accent)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
          <span style={{ fontSize: "13px", color: "var(--text-dim)" }}>Processando Grafo de Conhecimento...</span>
        </div>
      ) : isEmpty ? (
        /* ── Empty State ─────────────────────────────────────────────────────── */
        <div className="graphify-viewer-card" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "20px", height: "550px", textAlign: "center", padding: "32px" }}>
          <div style={{ fontSize: "56px", opacity: 0.4 }}>🌐</div>
          <div>
            <h3 style={{ fontSize: "16px", fontWeight: 700, color: "var(--text)", margin: "0 0 8px" }}>Grafo de Conhecimento Vazio</h3>
            <p style={{ fontSize: "13px", color: "var(--text-dim)", maxWidth: "420px", lineHeight: 1.6, margin: 0 }}>
              Nenhum nó foi indexado ainda. Clique em <strong style={{ color: "var(--accent)" }}>⚡ Indexar Workspace</strong> para processar a base de código e construir a rede automaticamente.
            </p>
          </div>
          <button
            type="button"
            onClick={handleIndex}
            disabled={isIndexing}
            className="btn-primary glow-button"
          >
            {isIndexing ? "⏳ Indexando..." : "⚡ Iniciar Indexação"}
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {selectedNode && (
            <div className="card" style={{ padding: "12px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "13px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ color: "var(--text-dim)" }}>Ego-grafo focado em:</span>
                <strong style={{ color: "var(--text)" }}>{selectedNode.name}</strong>
                <span className="graphify-badge" style={{ backgroundColor: "var(--accent-purple)" }}>
                  {selectedNode.entity_type}
                </span>
              </div>
              {selectedNode.summary && (
                <span style={{ color: "var(--text-muted)", fontSize: "12px", maxWidth: "300px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {selectedNode.summary}
                </span>
              )}
            </div>
          )}
          <GraphViewer
            nodes={nodes}
            edges={edges}
            onSelectNode={handleSelectNode}
            activeViewMode={activeTab}
          />
        </div>
      )}
    </div>
  );
}
