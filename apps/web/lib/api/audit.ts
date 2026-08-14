/**
 * Cliente real de auditoria — fala com `/api/audit` no backend.
 *
 * Sem `ipAddress`: o backend não rastreia IP de origem (uso local-first, uma
 * única chave de API) — o campo existia só no mock.
 */

import { get, post } from "@/lib/client";

export interface AuditEntry {
  id: string;
  created_at: string;
  actor: string;
  module: string;
  action: string;
  details: string;
  risk_level: "low" | "medium" | "critical";
  status: "success" | "denied" | "warning" | "error";
  session_id: string | null;
  project_slug: string | null;
  metadata: Record<string, unknown>;
}

export async function listAudit(filters?: {
  module?: string;
  risk_level?: string;
  q?: string;
  session_id?: string;
}): Promise<AuditEntry[]> {
  const params = new URLSearchParams();
  if (filters?.module) params.set("module", filters.module);
  if (filters?.risk_level) params.set("risk_level", filters.risk_level);
  if (filters?.q) params.set("q", filters.q);
  if (filters?.session_id) params.set("session_id", filters.session_id);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const { entries } = await get<{ entries: AuditEntry[] }>(`/api/audit${suffix}`);
  return entries;
}

export async function logAuditEvent(input: {
  actor: string;
  module: string;
  action: string;
  details?: string;
  risk_level?: "low" | "medium" | "critical";
  status?: "success" | "denied" | "warning";
}): Promise<AuditEntry> {
  return post<AuditEntry>("/api/audit/log", input);
}
