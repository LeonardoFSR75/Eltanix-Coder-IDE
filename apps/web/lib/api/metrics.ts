/**
 * Custo, token e economia agregados de `request_log` — `/api/metrics/*`.
 * Tipos espelham `api/routes/metrics.py`.
 */

import { get } from "@/lib/client";

export interface Summary {
  window_days: number;
  requests: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  cost_usd: number;
  avg_latency_ms: number | null;
  cache_hits: number;
  cache_hit_rate: number;
  savings: { tokens_saved: number; cost_saved_usd: number };
  unpriced_requests: number;
  budget: {
    daily_spent_usd: number;
    daily_limit_usd: number;
    monthly_spent_usd: number;
    monthly_limit_usd: number;
    hard_stop: boolean;
  };
}

export interface RecentRequest {
  id: string;
  created_at: string;
  source: string;
  requested_model: string;
  resolved_model: string | null;
  provider: string | null;
  status: string;
  error_type: string | null;
  latency_ms: number | null;
  total_tokens: number;
  cost_usd: number;
  cost_known: boolean;
  cache_hit: boolean;
  usage_estimated: boolean;
  fallback_from: string[];
}

export async function getMetricsSummary(days = 30): Promise<Summary> {
  return get<Summary>(`/api/metrics/summary?days=${days}`);
}

export async function getRecentRequests(limit = 50): Promise<RecentRequest[]> {
  const { requests } = await get<{ requests: RecentRequest[] }>(
    `/api/metrics/recent?limit=${limit}`,
  );
  return requests;
}
