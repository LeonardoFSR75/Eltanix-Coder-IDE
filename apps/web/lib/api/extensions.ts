/**
 * Cliente da API de Extensões e Auto-Update (`/api/extensions/*`).
 */

import { get, post } from "@/lib/client";

export interface ExtensionUpdateInfo {
  current_version?: string;
  latest_version?: string;
  published_at?: string;
  downloads?: string;
}

export interface ExtensionItem {
  id: string;
  name: string;
  publisher: string;
  version: string;
  description: string;
  category: string;
  icon: string;
  installed: boolean;
  active: boolean;
  isRecommended?: boolean;
  downloads?: string;
  rating?: number;
  latency_ms?: number;
  upstream_id?: string;
  repository_url?: string;
  features?: string[];
  hasUpdate?: boolean;
  updateInfo?: ExtensionUpdateInfo;
}

export interface ExtensionsCatalogResponse {
  extensions: ExtensionItem[];
  total_count: number;
  pending_updates_count: number;
  last_sync_timestamp: number;
  auto_update_enabled: boolean;
}

export interface SearchMarketplaceResponse {
  query: string;
  results: ExtensionItem[];
  count: number;
}

export async function getExtensionsCatalog(): Promise<ExtensionsCatalogResponse> {
  return get<ExtensionsCatalogResponse>("/api/extensions/catalog");
}

export async function syncExtensions(force: boolean = true): Promise<ExtensionsCatalogResponse> {
  return post<ExtensionsCatalogResponse>(`/api/extensions/sync?force=${force}`);
}

export async function toggleExtension(extensionId: string, active?: boolean): Promise<{ id: string; active: boolean }> {
  return post<{ id: string; active: boolean }>(`/api/extensions/${encodeURIComponent(extensionId)}/toggle`, {
    active,
  });
}

export async function updateExtension(extensionId: string): Promise<{ id: string; updated: boolean }> {
  return post<{ id: string; updated: boolean }>(`/api/extensions/${encodeURIComponent(extensionId)}/update`);
}

export async function updateAllExtensions(): Promise<{ updated_count: number; catalog: ExtensionsCatalogResponse }> {
  return post<{ updated_count: number; catalog: ExtensionsCatalogResponse }>("/api/extensions/update-all");
}

export async function setAutoUpdate(enabled: boolean): Promise<{ auto_update_enabled: boolean }> {
  return post<{ auto_update_enabled: boolean }>("/api/extensions/auto-update", { enabled });
}

export async function searchMarketplace(query: string): Promise<SearchMarketplaceResponse> {
  return get<SearchMarketplaceResponse>(`/api/extensions/search?q=${encodeURIComponent(query)}`);
}
