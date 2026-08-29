"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  get,
  login as apiLogin,
  loginMfa as apiLoginMfa,
  logout as apiLogout,
  type LoginResult,
} from "@/lib/client";

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

type LoginOutcome =
  | { ok: true }
  | { ok: false; mfaRequired: false }
  | { ok: false; mfaRequired: true; mfaToken: string };

interface AuthContextType {
  user: AuthUser | null;
  checking: boolean;
  /** `ok:true` = sessão pronta; `mfaRequired:true` = precisa do 2º fator. */
  login: (username: string, password: string) => Promise<LoginOutcome>;
  /** Completa o login em 2 etapas com o código do autenticador/recuperação. */
  completeMfa: (mfaToken: string, code: string) => Promise<boolean>;
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
    async (username: string, password: string): Promise<LoginOutcome> => {
      let result: LoginResult;
      try {
        result = await apiLogin(username, password);
      } catch {
        return { ok: false, mfaRequired: false };
      }
      if (result.mfaRequired) {
        return { ok: false, mfaRequired: true, mfaToken: result.mfaToken };
      }
      await refresh();
      return { ok: true };
    },
    [refresh],
  );

  const completeMfa = useCallback(
    async (mfaToken: string, code: string): Promise<boolean> => {
      try {
        await apiLoginMfa(mfaToken, code);
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
    <AuthContext.Provider value={{ user, checking, login, completeMfa, logout }}>
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
