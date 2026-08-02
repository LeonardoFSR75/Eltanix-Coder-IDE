"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/AuthContext";
import { useToast } from "@/components/Toast";

export default function LoginPage() {
  const router = useRouter();
  const { setApiKey, apiKeyValid, maskedKey } = useAuth();
  const { addToast } = useToast();

  const [apiKey, setApiKeyInput] = useState("");
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsValidating(true);
    setError(null);
    const ok = await setApiKey(apiKey);
    setIsValidating(false);
    if (ok) {
      addToast("Chave validada — conectado ao backend.", "success");
      router.push("/");
    } else {
      setError("Chave inválida ou backend inacessível. Confira SICOOBITO_API_KEY e tente de novo.");
    }
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
            Plataforma local-first com uma única chave de API compartilhada — sem contas de
            usuário, sem senha.
          </p>
        </div>

        {apiKeyValid && (
          <div className="already-logged-banner">
            <span>
              Você já está conectado{maskedKey ? ` com a chave ${maskedKey}` : " (backend sem chave configurada)"}.
            </span>
            <button type="button" className="btn-secondary-sm" onClick={() => router.push("/")}>
              Ir para Home
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="apikey-input">Chave de API do Sicoobito (SICOOBITO_API_KEY)</label>
            <input
              id="apikey-input"
              type="text"
              className="input-text font-mono"
              value={apiKey}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder="Deixe em branco se o backend não exige chave"
              autoComplete="off"
            />
          </div>
          {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
          <button
            type="submit"
            className="btn-primary btn-block btn-lg glow-button"
            disabled={isValidating}
          >
            {isValidating ? "Validando contra o backend..." : "Entrar"}
          </button>
        </form>

        <div className="login-footer">
          <div className="security-tag">
            <span className="pulse-dot-green" /> A chave fica só no seu navegador (localStorage) —
            o proxy do Next é quem a anexa nas chamadas ao backend.
          </div>
        </div>
      </div>
    </div>
  );
}
