/**
 * Sessões de login ativas do usuário — "onde estou logado" (F-5 da revisão
 * de segurança). Fala com `/api/auth/sessions` via o gateway.
 */

import { del, get } from "@/lib/client";

export interface AuthSessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
  user_agent: string | null;
  current: boolean;
}

export function listAuthSessions(): Promise<{ sessions: AuthSessionInfo[] }> {
  return get<{ sessions: AuthSessionInfo[] }>("/api/auth/sessions");
}

export function revokeAuthSession(id: string): Promise<{ status: string }> {
  return del<{ status: string }>(`/api/auth/sessions/${id}`);
}
