"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get, login as apiLogin, logout as apiLogout } from "@/lib/client";

/**
 * O backend agora exige login de sessão (`require_session` em
 * `api/deps.py`) — a chave de API compartilhada continua existindo, mas só
 * para integrações externas (CI, cline, cursor, aider), nunca para a UI web.
 * Este contexto reflete a sessão real: `user` vem de `GET /api/auth/me`
 * (cookie httpOnly, nunca localStorage).
 */

interface AuthUser {
  id: string;
  username: string;
  displayName: string | null;
}

interface MeResponse {
  id: string;
  username: string;
  display_name: string | null;
}

interface AuthContextType {
  user: AuthUser | null;
  checking: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    setChecking(true);
    try {
      const me = await get<MeResponse>("/api/auth/me");
      setUser({ id: me.id, username: me.username, displayName: me.display_name });
    } catch {
      // 401 é o caso normal de "não logado ainda" — qualquer outro status
      // também deixa `user` nulo, as páginas protegidas tratam igual.
      setUser(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      try {
        await apiLogin(username, password);
      } catch {
        return false;
      }
      await refresh();
      return true;
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, checking, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth deve ser usado dentro de AuthProvider");
  }
  return context;
}
