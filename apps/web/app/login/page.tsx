"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/AuthContext";
import { useToast } from "@/components/Toast";

export default function LoginPage() {
  const router = useRouter();
  const { login, completeMfa, user } = useAuth();
  const { addToast } = useToast();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Login em 2 etapas: quando a conta tem 2º fator, guardamos o desafio e
  // trocamos o formulário de senha pelo campo de código.
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsValidating(true);
    setError(null);
    const outcome = await login(username, password);
    setIsValidating(false);
    if (outcome.ok) {
      addToast("Login realizado.", "success");
      router.push("/projects");
    } else if (outcome.mfaRequired) {
      setMfaToken(outcome.mfaToken);
      setPassword("");
    } else {
      setError("Usuário ou senha inválidos.");
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mfaToken) return;
    setIsValidating(true);
    setError(null);
    const ok = await completeMfa(mfaToken, mfaCode.trim());
    setIsValidating(false);
    if (ok) {
      addToast("Login realizado.", "success");
      router.push("/projects");
    } else {
      setError("Código inválido ou desafio expirado.");
      setMfaCode("");
    }
  };

  const resetToPasswordStep = () => {
    setMfaToken(null);
    setMfaCode("");
    setError(null);
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
          <h1>Acesso ao Eltanix Coder IDE</h1>
          <p className="login-subtitle">
            Plataforma local-first — login obrigatório por usuário e senha.
          </p>
        </div>

        {user && (
          <div className="already-logged-banner">
            <span>Você já está conectado como {user.displayName || user.username}.</span>
            <button type="button" className="btn-secondary-sm" onClick={() => router.push("/projects")}>
              Ir para a Central de Projetos
            </button>
          </div>
        )}

        {mfaToken ? (
          <form onSubmit={handleMfaSubmit} className="login-form">
            <div className="form-group">
              <label htmlFor="mfa-code-input">Código de verificação</label>
              <input
                id="mfa-code-input"
                type="text"
                inputMode="numeric"
                className="input-text font-mono"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="000000"
                autoComplete="one-time-code"
                autoFocus
              />
              <p className="text-xs text-muted" style={{ marginTop: 6 }}>
                Abra seu app autenticador e digite o código de 6 dígitos. Sem acesso a ele? Use um
                código de recuperação.
              </p>
            </div>
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button
              type="submit"
              className="btn-primary btn-block btn-lg glow-button"
              disabled={isValidating || mfaCode.trim().length < 6}
            >
              {isValidating ? "Verificando..." : "Verificar"}
            </button>
            <button type="button" className="btn-secondary-sm btn-block" onClick={resetToPasswordStep}>
              ← Voltar
            </button>
          </form>
        ) : (
          <form onSubmit={handleSubmit} className="login-form">
            <div className="form-group">
              <label htmlFor="username-input">Usuário</label>
              <input
                id="username-input"
                type="text"
                className="input-text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
              />
            </div>
            <div className="form-group">
              <label htmlFor="password-input">Senha</label>
              <input
                id="password-input"
                type="password"
                className="input-text"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button
              type="submit"
              className="btn-primary btn-block btn-lg glow-button"
              disabled={isValidating || !username || !password}
            >
              {isValidating ? "Entrando..." : "Entrar"}
            </button>
          </form>
        )}

        <div className="login-footer">
          <div className="security-tag">
            <span className="pulse-dot-green" /> A sessão fica num cookie httpOnly — o servidor Next
            nunca expõe o token ao JavaScript do browser.
          </div>
        </div>
      </div>
    </div>
  );
}
