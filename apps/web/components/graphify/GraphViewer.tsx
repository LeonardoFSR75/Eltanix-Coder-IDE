"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

export interface GraphNode {
  id: string;
  name: string;
  entity_type: string;
  canonical_id: string;
  summary?: string;
  pagerank?: number;
  is_orphan?: boolean;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  layer: number;
  weight: number;
}

interface GraphViewerProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onSelectNode?: (node: GraphNode) => void;
  activeViewMode?: "universe" | "domain" | "concept" | "architecture" | "brain";
}

const TYPE_COLORS: Record<string, string> = {
  Note: "#38bdf8", // Cyan / Blue
  Concept: "#c084fc", // Obsidian Purple
  Module: "#34d399", // Emerald
  Class: "#fbbf24", // Amber
  Function: "#f472b6", // Pink
  ADR: "#f87171", // Red
  Commit: "#94a3b8", // Slate
  Author: "#22d3ee", // Cyan
  Document: "#2dd4bf", // Teal
  default: "#818cf8",
};

function getTypesForViewMode(mode: string): string[] | null {
  switch (mode) {
    case "domain":
      return ["Module", "Class", "Document"];
    case "concept":
      return ["Concept", "Note", "ADR"];
    case "architecture":
      return ["Module", "Class", "Function", "ADR"];
    case "brain":
      return ["Note", "Concept", "Author", "Document"];
    case "universe":
    default:
      return null;
  }
}

/** Formata caminhos longos de arquivo para um rótulo curto no canvas */
function formatNodeLabel(name: string): string {
  if (!name) return "";
  if (name.includes("/") || name.includes("\\")) {
    const parts = name.replace(/\\/g, "/").split("/").filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
    }
    return parts[parts.length - 1] || name;
  }
  return name;
}

export default function GraphViewer({
  nodes: initialNodes,
  edges,
  onSelectNode,
  activeViewMode = "universe",
}: GraphViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [zoom, setZoom] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const isDraggingCanvas = useRef<boolean>(false);
  const draggedNodeRef = useRef<GraphNode | null>(null);
  const dragStart = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Controle de Energia da Física (Simulação com Arrefecimento / Alpha Decay)
  const alphaRef = useRef<number>(1.0);

  // Filtrar nós de acordo com a aba de visão ativa
  const filteredNodes = useMemo(() => {
    const allowed = getTypesForViewMode(activeViewMode);
    if (!allowed) return initialNodes;
    return initialNodes.filter((n) => allowed.includes(n.entity_type));
  }, [initialNodes, activeViewMode]);

  const visibleNodeIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);

  const filteredEdges = useMemo(() => {
    return edges.filter(
      (e) => visibleNodeIds.has(e.source_id) && visibleNodeIds.has(e.target_id)
    );
  }, [edges, visibleNodeIds]);

  // Force-directed simulation nodes
  const simNodesRef = useRef<GraphNode[]>([]);

  // Inicializar posições dos nós filtrados em layout radial + Reset do Alpha
  useEffect(() => {
    const container = containerRef.current;
    const width = container ? container.clientWidth : 800;
    const height = container ? container.clientHeight : 600;

    simNodesRef.current = filteredNodes.map((n, i) => {
      const angle = (i / Math.max(filteredNodes.length, 1)) * 2 * Math.PI;
      const radius = 160 + Math.random() * 120;
      return {
        ...n,
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      };
    });

    alphaRef.current = 1.0; // Restaura energia para estabilizar novo layout
  }, [filteredNodes]);

  // Redimensionar Canvas com HiDPI
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const resizeObserver = new ResizeObserver(() => {
      const dpr = window.devicePixelRatio || 1;
      const width = container.clientWidth;
      const height = container.clientHeight;

      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    });

    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, []);

  // Loop de Renderização & Física Estável (Alpha Cooling)
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;

    const render = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = container.clientWidth;
      const height = container.clientHeight;
      const alpha = alphaRef.current;
      const nodes = simNodesRef.current;

      // ── Executar física APENAS se houver energia residual (alpha > 0.001) ─────
      if (alpha > 0.001) {
        const kRepulsion = 600;
        const kAttraction = 0.03;
        const centerX = width / 2;
        const centerY = height / 2;

        // 1. Força de repulsão entre nós visíveis
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const dx = nodes[j].x! - nodes[i].x!;
            const dy = nodes[j].y! - nodes[i].y!;
            const dist = Math.max(20, Math.sqrt(dx * dx + dy * dy));
            const force = (kRepulsion / (dist * dist)) * alpha;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;

            if (draggedNodeRef.current?.id !== nodes[i].id) {
              nodes[i].vx! -= fx;
              nodes[i].vy! -= fy;
            }
            if (draggedNodeRef.current?.id !== nodes[j].id) {
              nodes[j].vx! += fx;
              nodes[j].vy! += fy;
            }
          }
        }

        // 2. Força de atração ao longo das arestas filtradas
        filteredEdges.forEach((edge) => {
          const src = nodes.find((n) => n.id === edge.source_id);
          const tgt = nodes.find((n) => n.id === edge.target_id);
          if (src && tgt) {
            const dx = tgt.x! - src.x!;
            const dy = tgt.y! - src.y!;
            const dist = Math.max(20, Math.sqrt(dx * dx + dy * dy));
            const force = (dist - 100) * kAttraction * alpha;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;

            if (draggedNodeRef.current?.id !== src.id) {
              src.vx! += fx;
              src.vy! += fy;
            }
            if (draggedNodeRef.current?.id !== tgt.id) {
              tgt.vx! -= fx;
              tgt.vy! -= fy;
            }
          }
        });

        // 3. Gravidade central suave (mantém nós agrupados no centro)
        nodes.forEach((n) => {
          if (draggedNodeRef.current?.id !== n.id) {
            const dx = centerX - n.x!;
            const dy = centerY - n.y!;
            n.vx! += dx * 0.001 * alpha;
            n.vy! += dy * 0.001 * alpha;
          }
        });

        // 4. Atualizar posições & travar velocidade máxima (evita saltos)
        const maxSpeed = 5 * alpha;
        nodes.forEach((n) => {
          if (draggedNodeRef.current?.id !== n.id) {
            n.vx! *= 0.85;
            n.vy! *= 0.85;
            n.vx! = Math.max(-maxSpeed, Math.min(maxSpeed, n.vx!));
            n.vy! = Math.max(-maxSpeed, Math.min(maxSpeed, n.vy!));
            n.x! += n.vx!;
            n.y! += n.vy!;
          }
        });

        // Arrefecimento gradual da física até congelar em repouso
        alphaRef.current *= 0.95;
      }

      // ── Limpar e Desenhar no Canvas ─────────────────────────────────────────
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.translate(pan.x, pan.y);
      ctx.scale(zoom, zoom);

      // Renderizar Arestas (Linhas)
      filteredEdges.forEach((edge) => {
        const src = nodes.find((n) => n.id === edge.source_id);
        const tgt = nodes.find((n) => n.id === edge.target_id);
        if (src && tgt) {
          ctx.beginPath();
          ctx.moveTo(src.x!, src.y!);
          ctx.lineTo(tgt.x!, tgt.y!);
          ctx.strokeStyle =
            edge.layer === 1
              ? "rgba(56, 189, 248, 0.25)"
              : edge.layer === 2
              ? "rgba(192, 132, 252, 0.25)"
              : "rgba(52, 211, 153, 0.25)";
          ctx.lineWidth = edge.layer === 1 ? 1.5 : 1;
          ctx.stroke();

          // Rótulo da relação ao passar o mouse
          if (hoveredNode && (hoveredNode.id === src.id || hoveredNode.id === tgt.id)) {
            const midX = (src.x! + tgt.x!) / 2;
            const midY = (src.y! + tgt.y!) / 2;
            ctx.font = "10px var(--font-mono, monospace)";
            ctx.fillStyle = "#94a3b8";
            ctx.fillText(edge.relation_type, midX, midY);
          }
        }
      });

      // Renderizar Nós (Círculos & Rótulos)
      nodes.forEach((n) => {
        const color =
          activeViewMode === "brain" && n.is_orphan
            ? "#f87171"
            : TYPE_COLORS[n.entity_type] || TYPE_COLORS.default;

        const isSelected = selectedNode?.id === n.id;
        const isHovered = hoveredNode?.id === n.id;
        const radius = 7 + (n.pagerank ? n.pagerank * 35 : 3) + (isSelected ? 5 : 0);

        // Brilho exterior (Glow) se selecionado/hover
        if (isSelected || isHovered) {
          ctx.beginPath();
          ctx.arc(n.x!, n.y!, radius + 6, 0, 2 * Math.PI);
          ctx.fillStyle = isSelected ? "rgba(56, 189, 248, 0.3)" : "rgba(255, 255, 255, 0.15)";
          ctx.fill();
        }

        // Círculo principal do nó
        ctx.beginPath();
        ctx.arc(n.x!, n.y!, radius, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = isSelected ? "#ffffff" : "rgba(255, 255, 255, 0.3)";
        ctx.lineWidth = isSelected ? 2.5 : 1;
        ctx.stroke();

        // Label legível do Nó
        const displayLabel = formatNodeLabel(n.name);
        ctx.font = isSelected
          ? "bold 12px var(--font-mono, monospace)"
          : "11px var(--font-mono, monospace)";

        // Contorno escuro para garantir legibilidade em qualquer fundo
        ctx.strokeStyle = "#030406";
        ctx.lineWidth = 3;
        ctx.strokeText(displayLabel, n.x! + radius + 6, n.y! + 4);

        ctx.fillStyle = isSelected ? "#ffffff" : isHovered ? "#38bdf8" : "#cbd5e1";
        ctx.fillText(displayLabel, n.x! + radius + 6, n.y! + 4);
      });

      ctx.restore();

      animId = requestAnimationFrame(render);
    };

    render();

    return () => cancelAnimationFrame(animId);
  }, [filteredEdges, selectedNode, hoveredNode, zoom, pan, activeViewMode]);

  // Interação do Mouse: Drag em Nó ou Pan na Tela
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = (e.clientX - rect.left - pan.x) / zoom;
    const mouseY = (e.clientY - rect.top - pan.y) / zoom;

    const found = simNodesRef.current.find((n) => {
      const dx = n.x! - mouseX;
      const dy = n.y! - mouseY;
      return Math.sqrt(dx * dx + dy * dy) <= 16;
    });

    if (found) {
      draggedNodeRef.current = found;
    } else {
      isDraggingCanvas.current = true;
      dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    if (draggedNodeRef.current) {
      const rect = canvas.getBoundingClientRect();
      const mouseX = (e.clientX - rect.left - pan.x) / zoom;
      const mouseY = (e.clientY - rect.top - pan.y) / zoom;

      draggedNodeRef.current.x = mouseX;
      draggedNodeRef.current.y = mouseY;
      draggedNodeRef.current.vx = 0;
      draggedNodeRef.current.vy = 0;

      // Re-ativa levemente a física para ajustar vizinhos suavemente
      alphaRef.current = Math.max(alphaRef.current, 0.15);
      return;
    }

    if (isDraggingCanvas.current) {
      setPan({ x: e.clientX - dragStart.current.x, y: e.clientY - dragStart.current.y });
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const mouseX = (e.clientX - rect.left - pan.x) / zoom;
    const mouseY = (e.clientY - rect.top - pan.y) / zoom;

    const found = simNodesRef.current.find((n) => {
      const dx = n.x! - mouseX;
      const dy = n.y! - mouseY;
      return Math.sqrt(dx * dx + dy * dy) <= 16;
    });

    setHoveredNode(found || null);
  };

  const handleMouseUp = () => {
    isDraggingCanvas.current = false;
    draggedNodeRef.current = null;
  };

  const handleClick = () => {
    if (hoveredNode) {
      setSelectedNode(hoveredNode);
      if (onSelectNode) onSelectNode(hoveredNode);
    }
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    alphaRef.current = 1.0; // Restaura energia para reagrupar o grafo suavemente
  };

  return (
    <div ref={containerRef} className="graphify-viewer-card">
      {/* Legenda dos Tipos de Nós Visíveis */}
      <div className="graphify-legend-bar">
        {Object.entries(TYPE_COLORS)
          .filter(([key]) => {
            if (key === "default") return false;
            const allowed = getTypesForViewMode(activeViewMode);
            return !allowed || allowed.includes(key);
          })
          .map(([type, color]) => (
            <div key={type} className="graphify-legend-item">
              <span className="graphify-legend-dot" style={{ backgroundColor: color }} />
              <span>{type}</span>
            </div>
          ))}
      </div>

      {/* Controles Flutuantes de Zoom / Pan */}
      <div className="graphify-controls-overlay">
        <button
          type="button"
          onClick={() => setZoom((z) => Math.min(z + 0.2, 3))}
          className="graphify-control-btn"
          title="Aumentar Zoom"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => setZoom((z) => Math.max(z - 0.2, 0.3))}
          className="graphify-control-btn"
          title="Diminuir Zoom"
        >
          -
        </button>
        <button
          type="button"
          onClick={resetView}
          className="graphify-control-btn"
          title="Resetar & Reagrupar"
          style={{ fontSize: "11px" }}
        >
          🎯
        </button>
      </div>

      {/* Drawer de Detalhes do Nó Selecionado */}
      {selectedNode && (
        <div className="graphify-drawer">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
            <span
              className="graphify-badge"
              style={{ backgroundColor: TYPE_COLORS[selectedNode.entity_type] || TYPE_COLORS.default }}
            >
              {selectedNode.entity_type}
            </span>
            <button
              type="button"
              onClick={() => setSelectedNode(null)}
              className="btn-text-sm"
              style={{ padding: 0 }}
            >
              ✕
            </button>
          </div>
          <h4 style={{ fontSize: "14px", fontWeight: 700, color: "var(--text)", margin: "0 0 4px", wordBreak: "break-all" }}>
            {selectedNode.name}
          </h4>
          <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--accent)", margin: "0 0 8px", wordBreak: "break-all" }}>
            {selectedNode.canonical_id}
          </p>
          {selectedNode.summary && (
            <p style={{ fontSize: "12px", color: "var(--text-dim)", lineHeight: 1.5, margin: 0, display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
              {selectedNode.summary}
            </p>
          )}
        </div>
      )}

      {/* Elemento Canvas */}
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onClick={handleClick}
        style={{ cursor: isDraggingCanvas.current ? "grabbing" : "grab" }}
      />
    </div>
  );
}
