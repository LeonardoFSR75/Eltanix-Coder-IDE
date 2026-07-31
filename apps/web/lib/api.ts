/**
 * Cliente do backend, usado apenas em Server Components.
 *
 * A chave da API fica no processo Next e nunca chega ao browser: as páginas são
 * renderizadas no servidor e só o HTML resultante desce. Nenhuma chamada ao
 * gateway parte do cliente — por isso não há variável `NEXT_PUBLIC_*` aqui.
 */

const BASE_URL = process.env.SICOOBITO_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.SICOOBITO_API_KEY ?? "";

export type FetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

export async function apiGet<T>(path: string): Promise<FetchResult<T>> {
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      headers: API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {},
      // Métricas de custo envelhecem rápido; cache aqui só confundiria.
      cache: "no-store",
    });

    if (!response.ok) {
      return {
        ok: false,
        error: `${response.status} ${response.statusText} em ${path}`,
      };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      error: `Backend inacessível em ${BASE_URL}: ${message}`,
    };
  }
}

// ── Tipos espelhando as respostas do backend ────────────────────────────────

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

export interface ModelUsage {
  model: string;
  provider: string | null;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  avg_latency_ms: number | null;
  errors: number;
}

export interface SourceUsage {
  source: string;
  requests: number;
  total_tokens: number;
  cost_usd: number;
}

export interface Savings {
  window_days: number;
  by_technique: { technique: string; tokens_saved: number }[];
  cache: { hits: number; tokens_saved: number; cost_saved_usd: number };
  by_complexity: { complexity: string; requests: number; cost_usd: number }[];
}

export interface TimeseriesPoint {
  day: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  cost_saved_usd: number;
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
  success_rate?: number;
  latency_p50_ms?: number | null;
  latency_p95_ms?: number | null;
  unavailable_reason?: string | null;
}

export interface CatalogModel {
  id: string;
  provider: string;
  context_window: number;
  tags: string[];
  capabilities: string[];
  enabled: boolean;
  available: boolean;
  unavailable_reason: string | null;
  price: {
    input: number | null;
    output: number | null;
    cache_read: number | null;
    cache_write: number | null;
  } | null;
}

export interface CatalogProfile {
  name: string;
  strategy: string;
  models: string[];
  weights: Record<string, number>;
  is_default: boolean;
}

/** Campo-segredo nunca traz `value`; campo de endpoint/URL nunca traz `masked`. */
export interface CredentialField {
  configured: boolean;
  value: string | null;
  masked: string | null;
}

export interface CredentialsView {
  ollama_base_url: CredentialField;
  azure_api_base: CredentialField;
  azure_api_key: CredentialField;
  databricks_host: CredentialField;
  databricks_token: CredentialField;
  openai_api_key: CredentialField;
  anthropic_api_key: CredentialField;
  github_token: CredentialField;
}

/** Um modelo visto na API de listagem do provedor, ainda fora do catálogo. */
export interface DiscoveredModelCandidate {
  suggested_id: string;
  provider: string;
  raw_name: string;
  model: string | null;
  deployment: string | null;
  endpoint: string | null;
  mode: string | null;
  context_window: number;
  tags: string[];
  capabilities: string[];
  /** Campos que são palpite, não dado confirmado pelo provedor — a revisão avisa sobre esses. */
  estimated_fields: string[];
  /** Presente só em `already_cataloged`: sob qual id o modelo já está cadastrado. */
  existing_id?: string;
}

export interface DiscoverResponse {
  provider: string;
  new: DiscoveredModelCandidate[];
  already_cataloged: DiscoveredModelCandidate[];
  error: string | null;
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
