/**
 * Busca leve de usuários da instância (`/api/auth/users/search`) — usada pelo
 * seletor de convite da aba "Membros" do Hub 360° (`/api/projects/{slug}/members`).
 * Ao contrário de `/api/auth/users` (admin-only), esta rota é visível a
 * qualquer usuário autenticado, mas devolve só `id`/`username`/`display_name`.
 */

import { get } from "@/lib/client";

export interface UserSearchResult {
  id: string;
  username: string;
  display_name: string | null;
}

export async function searchUsers(query: string): Promise<UserSearchResult[]> {
  const data = await get<{ users: UserSearchResult[] }>(
    `/api/auth/users/search?q=${encodeURIComponent(query)}`
  );
  return data.users;
}
