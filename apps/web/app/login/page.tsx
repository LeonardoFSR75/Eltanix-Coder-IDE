"use client";

import React, { useState } from "react";
import { useAuth, UserProfile } from "@/components/providers/AuthContext";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";

export default function LoginPage() {
  // ✅ FIX: useRouter chamado no top-level do componente (Regra dos Hooks)
  const router = useRouter();
  const { login, user } = useAuth();
  const { addToast } = useToast();

  const [authMode, setAuthMode] = useState<"passkey" | "password" | "apikey">("passkey");
  const [email, setEmail] = useState("leonardo@sicoobito.local");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [selectedRole, setSelectedRole] = useState<UserProfile["role"]>("Engenheiro de IA");
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  const handleLoginSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsAuthenticating(true);
    if (apiKey) {
      localStorage.setItem("sicoobito_api_key", apiKey);
    }

    setTimeout(() => {
      login(email, selectedRole, authMode);
      setIsAuthenticating(false);
      addToast("Autenticado com sucesso! Bem-vindo ao SicoobitoCode.", "success");
      router.push("/");
    }, 800);
  };

  const handlePasskeySimulate = () => {
    setIsAuthenticating(true);
    setTimeout(() => {
      login("biometria@sicoobito.local", selectedRole, "passkey");
      setIsAuthenticating(false);
      addToast("Biometria / Passkey verificada com sucesso via hardware seguro!", "success");
      router.push("/");
    }, 1000);
  };

  return (
    <div className="login-container">
      <div className="glow-sphere sphere-1" />
      <div className="glow-sphere sphere-2" />

      <div className="login-card">
        <div className="login-header">
          <div className="login-logo-ring">
            <span className="login-logo-text">S</span>
          </div>
          <h1>Acesso ao SicoobitoCode</h1>
          <p className="login-subtitle">
            Plataforma Agêntica Local-First com RAG, ChromaDB &amp; Redes Neurais
          </p>
        </div>

        {user && (
          <div className="already-logged-banner">
            <span>Você já está conectado como <strong>{user.name}</strong> ({user.role})</span>
            <button
              type="button"
              className="btn-secondary-sm"
              onClick={() => router.push("/")}
            >
              Ir para Home
            </button>
          </div>
        )}

        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab ${authMode === "passkey" ? "active" : ""}`}
            onClick={() => setAuthMode("passkey")}
          >
            🛡️ Biometria / Passkey
          </button>
          <button
            type="button"
            className={`auth-tab ${authMode === "password" ? "active" : ""}`}
            onClick={() => setAuthMode("password")}
          >
            🔑 Credenciais
          </button>
          <button
            type="button"
            className={`auth-tab ${authMode === "apikey" ? "active" : ""}`}
            onClick={() => setAuthMode("apikey")}
          >
            ⚡ Chave API
          </button>
        </div>

        <form onSubmit={handleLoginSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="role-select">Perfil de Acesso</label>
            <select
              id="role-select"
              value={selectedRole}
              onChange={(e) => setSelectedRole(e.target.value as UserProfile["role"])}
              className="input-select"
            >
              <option value="Engenheiro de IA">⚡ Engenheiro de IA</option>
              <option value="Admin">🛡️ Administrador do Sistema</option>
              <option value="Auditor">🔍 Auditor de Segurança</option>
              <option value="Desenvolvedor">💻 Desenvolvedor Fullstack</option>
            </select>
          </div>

          {authMode === "passkey" && (
            <div className="passkey-box">
              <div className="fingerprint-icon">🖐️</div>
              <h3>Autenticação por Hardware Seguro</h3>
              <p>Utilize a digital do dispositivo, FIDO2 ou Windows Hello para entrar com 0 latência.</p>
              <button
                type="button"
                className="btn-primary btn-block btn-lg glow-button"
                onClick={handlePasskeySimulate}
                disabled={isAuthenticating}
              >
                {isAuthenticating ? "Verificando Hardware..." : "Autenticar via Passkey"}
              </button>
            </div>
          )}

          {authMode === "password" && (
            <>
              <div className="form-group">
                <label htmlFor="email-input">E-mail Corporativo</label>
                <input
                  id="email-input"
                  type="email"
                  className="input-text"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="password-input">Senha Principal</label>
                <input
                  id="password-input"
                  type="password"
                  className="input-text"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  required
                />
              </div>
              <button
                type="submit"
                className="btn-primary btn-block btn-lg glow-button"
                disabled={isAuthenticating}
              >
                {isAuthenticating ? "Validando no Banco..." : "Entrar no Sistema"}
              </button>
            </>
          )}

          {authMode === "apikey" && (
            <>
              <div className="form-group">
                <label htmlFor="apikey-input">Sicoobito API Key (Bearer Token)</label>
                <input
                  id="apikey-input"
                  type="text"
                  className="input-text font-mono"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="scbt_live_..."
                  required
                />
              </div>
              <button
                type="submit"
                className="btn-primary btn-block btn-lg glow-button"
                disabled={isAuthenticating}
              >
                {isAuthenticating ? "Autenticando Chave..." : "Entrar com Chave API"}
              </button>
            </>
          )}
        </form>

        <div className="login-footer">
          <div className="security-tag">
            <span className="pulse-dot-green" /> Conexão Criptografada TLS 1.3 · Postgres 17 &amp; ChromaDB
          </div>
        </div>
      </div>
    </div>
  );
}
