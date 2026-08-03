/**
 * Spans recentes de execução (ferramentas do agente + buscas RAG) — fala com
 * `/api/telemetry` no backend. Complementa `/api/metrics` (custo/tokens de
 * LLM) e `/api/health/providers` (circuit breaker), que já cobrem a camada
 * de modelos.
 */

import { get } from "@/lib/client";

export type TraceKind = "tool" | "rag";
export type TraceStatus = "ok" | "error";

export interface TraceEntry {
  ts: number;
  kind: TraceKind;
  name: string;
  latency_ms: number;
  status: TraceStatus;
  session_id: string;
  error: string | null;
}

export async function listRecentTraces(limit = 50): Promise<TraceEntry[]> {
  const { entries } = await get<{ entries: TraceEntry[] }>(
    `/api/telemetry/recent?limit=${limit}`,
  );
  return entries;
}
