"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get } from "@/lib/client";

/**
 * O backend usa uma única chave de API compartilhada (`SICOOBITO_API_KEY`),
 * não contas de usuário — ver `api/deps.py::require_api_key`. Este contexto
 * reflete exatamente isso: guarda a chave local e se ela é válida contra o
 * backend, nada de perfil, papel ou avatar fabricados.
 */

const STORAGE_KEY = "sicoobito_api_key";

function maskKey(key: string): string {
  return key.length <= 4 ? "••••" : `••••${key.slice(-4)}`;
}

interface AuthContextType {
  hasApiKey: boolean;
  // null enquanto a primeira checagem contra o backend não terminou.
  apiKeyValid: boolean | null;
  checking: boolean;
  maskedKey: string | null;
  setApiKey: (key: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [hasApiKey, setHasApiKey] = useState(false);
  const [maskedKey, setMaskedKey] = useState<string | null>(null);
  const [apiKeyValid, setApiKeyValid] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(true);

  // Sem chave, `require_api_key` ainda pode aceitar a chamada — se o
  // backend não tiver `SICOOBITO_API_KEY` configurada, fica aberto de
  // propósito para uso estritamente local. Por isso a validação é sempre
  // "chamar /health e ver o que volta", não "existe uma chave salva".
  const validate = useCallback(async (): Promise<boolean> => {
    setChecking(true);
    try {
      await get("/api/health");
      setApiKeyValid(true);
      return true;
    } catch {
      setApiKeyValid(false);
      return false;
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    setHasApiKey(!!stored);
    setMaskedKey(stored ? maskKey(stored) : null);
    validate();
  }, [validate]);

  const setApiKey = useCallback(
    async (key: string): Promise<boolean> => {
      const trimmed = key.trim();
      if (trimmed) {
        localStorage.setItem(STORAGE_KEY, trimmed);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
      setHasApiKey(!!trimmed);
      setMaskedKey(trimmed ? maskKey(trimmed) : null);
      return validate();
    },
    [validate],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setHasApiKey(false);
    setMaskedKey(null);
    setApiKeyValid(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ hasApiKey, apiKeyValid, checking, maskedKey, setApiKey, logout }}
    >
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
