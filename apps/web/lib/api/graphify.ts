/**
 * Cliente para o Graphify Engine — `/api/graphify/*`.
 *
 * Usa o mesmo proxy autenticado do restante da plataforma (lib/client.ts)
 * para que a chave da API nunca chegue ao browser.
 */

import { get, post } from "@/lib/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  name: string;
  entity_type: string;
  canonical_id: string;
  summary?: string;
  pagerank?: number;
  is_orphan?: boolean;
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  layer: number;
  weight: number;
}

export interface GraphMetrics {
  total_nodes: number;
  total_edges: number;
  orphan_nodes_count: number;
  orphan_percentage: number;
  density: number;
}

export interface GraphQueryResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  answer?: string;
}

export interface EgoGraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function listGraphNodes(workspace = "default", limit = 100): Promise<GraphNode[]> {
  return get<GraphNode[]>(
    `/api/graphify/nodes?workspace=${encodeURIComponent(workspace)}&limit=${limit}`,
  );
}

export async function listGraphEdges(workspace = "default", limit = 500): Promise<GraphEdge[]> {
  return get<GraphEdge[]>(
    `/api/graphify/edges?workspace=${encodeURIComponent(workspace)}&limit=${limit}`,
  );
}

export async function getGraphMetrics(workspace = "default"): Promise<GraphMetrics> {
  return get<GraphMetrics>(`/api/graphify/metrics?workspace=${encodeURIComponent(workspace)}`);
}

export async function queryGraph(
  query: string,
  workspace = "default",
  topK = 15,
): Promise<GraphQueryResult> {
  return post<GraphQueryResult>("/api/graphify/query", {
    query,
    workspace,
    top_k: topK,
  });
}

export async function getEgoGraph(
  nodeId: string,
  workspace = "default",
  depth = 2,
): Promise<EgoGraphResult> {
  return get<EgoGraphResult>(
    `/api/graphify/nodes/${encodeURIComponent(nodeId)}/ego?workspace=${encodeURIComponent(workspace)}&depth=${depth}`,
  );
}

export async function indexWorkspace(workspace = "default"): Promise<{ status: string; nodes_indexed: number }> {
  return post<{ status: string; nodes_indexed: number }>("/api/graphify/index", { workspace });
}
