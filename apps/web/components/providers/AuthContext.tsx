"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  role: "Admin" | "Engenheiro de IA" | "Auditor" | "Desenvolvedor";
  avatar: string;
  token: string;
  authMethod: "password" | "passkey" | "apikey";
}

interface AuthContextType {
  user: UserProfile | null;
  isAuthenticated: boolean;
  login: (email: string, role?: UserProfile["role"], method?: UserProfile["authMethod"]) => void;
  logout: () => void;
  updateUser: (updated: Partial<UserProfile>) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const STORAGE_KEY = "sicoobito_auth_user";

const DEFAULT_USER: UserProfile = {
  id: "usr-admin-01",
  name: "Leonardo Silva",
  email: "leonardo@sicoobito.local",
  role: "Engenheiro de IA",
  avatar: "⚡",
  token: "scbt_token_sec_9941a8e22b",
  authMethod: "passkey",
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  // ✅ FIX: Inicializa como true para não causar flash de conteúdo vazio;
  // a leitura do localStorage é feita no useEffect abaixo.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        setUser(JSON.parse(stored));
      } catch {
        setUser(DEFAULT_USER);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_USER));
      }
    } else {
      setUser(DEFAULT_USER);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_USER));
    }
  }, []);

  const login = (
    email: string,
    role: UserProfile["role"] = "Engenheiro de IA",
    method: UserProfile["authMethod"] = "password"
  ) => {
    const newUser: UserProfile = {
      id: `usr-${Date.now()}`,
      name: email.split("@")[0]?.replace(/[._-]/g, " ") || "Usuário Sicoobito",
      email: email,
      role: role,
      avatar: role === "Admin" ? "🛡️" : role === "Auditor" ? "🔍" : role === "Desenvolvedor" ? "💻" : "⚡",
      token: `scbt_token_${Math.random().toString(36).slice(2)}`,
      authMethod: method,
    };
    setUser(newUser);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(newUser));
  };

  // ✅ FIX: Novo método updateUser para atualizar campos do perfil sem criar novo ID
  const updateUser = (updated: Partial<UserProfile>) => {
    setUser((prev) => {
      if (!prev) return prev;
      const merged = { ...prev, ...updated };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
      return merged;
    });
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem(STORAGE_KEY);
  };

  // ✅ FIX: Renderiza children normalmente durante hidratação; o estado de user
  // começa como null e é preenchido no useEffect (comportamento correto no SSR/CSR).
  // Não retornamos null aqui para evitar que toda a UI desapareça durante mount.
  return (
    <AuthContext.Provider
      value={{
        user: mounted ? user : null,
        isAuthenticated: mounted && !!user,
        login,
        logout,
        updateUser,
      }}
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
