/**
 * Saúde do gateway e dos provedores — `/api/health`, `/api/health/providers`,
 * reset de circuit breaker e limpeza do cache exato. Tipos espelham
 * `RouterEngine.healthcheck()` (apps/api/src/sicoobito/router/engine.py).
 */

import { get, post } from "@/lib/client";

export interface HealthStatus {
  status: string;
  models_total: number;
  models_usable: number;
  profiles: string[];
  cache_enabled: boolean;
  pricing_updated_at: string | null;
}

export interface ProviderCheck {
  model: string;
  provider?: string;
  enabled?: boolean;
  ok: boolean;
  detail?: string | null;
  probe_latency_ms?: number | null;
  circuit_open?: boolean;
  cooldown_remaining_s?: number;
  consecutive_fails?: number;
  successes?: number;
  failures?: number;
  success_rate?: number;
  latency_p50_ms?: number | null;
  latency_p95_ms?: number | null;
  unavailable_reason?: string | null;
}

export interface ProvidersHealthResponse {
  healthy: number;
  total: number;
  providers: ProviderCheck[];
}

export async function getHealth(): Promise<HealthStatus> {
  return get<HealthStatus>("/api/health");
}

export async function getProvidersHealth(): Promise<ProvidersHealthResponse> {
  return get<ProvidersHealthResponse>("/api/health/providers");
}

export async function resetCircuit(modelId: string): Promise<{ model: string; reset: boolean }> {
  // A rota usa `{model_id:path}` — o id do modelo (que pode ter "/", ex.
  // "ollama/qwen2.5-coder:7b") entra cru, sem encodeURIComponent.
  return post<{ model: string; reset: boolean }>(`/api/providers/${modelId}/reset`);
}

export async function clearCache(): Promise<{ removed: number }> {
  return post<{ removed: number }>("/api/cache/clear");
}
