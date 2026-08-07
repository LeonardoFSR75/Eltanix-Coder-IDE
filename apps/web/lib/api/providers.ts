/**
 * Catálogo de modelos, perfis de roteamento e credenciais de provedor —
 * `/api/providers*`. Tipos espelham `api/routes/health.py` (o módulo do
 * backend que serve a tela `/providers`, apesar do nome do arquivo).
 */

import { get } from "@/lib/client";

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

export interface CatalogResponse {
  models: CatalogModel[];
  profiles: CatalogProfile[];
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
  groq_api_key: CredentialField;
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

export async function getCatalog(): Promise<CatalogResponse> {
  return get<CatalogResponse>("/api/providers");
}

export async function getCredentials(): Promise<CredentialsView> {
  const { credentials } = await get<{ credentials: CredentialsView }>(
    "/api/providers/credentials",
  );
  return credentials;
}
