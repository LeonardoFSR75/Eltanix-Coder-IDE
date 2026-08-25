"use client";

import React, { useState, useEffect } from "react";
import { useToast } from "@/components/Toast";
import {
  getGitHubConfig,
  testGitHubToken,
  updateGitHubConfig,
  type GitHubConfigResponse,
} from "@/lib/api/git-config";

export function GitHubAccountCard() {
  const { addToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const [config, setConfig] = useState<GitHubConfigResponse | null>(null);
  const [inputToken, setInputToken] = useState("");
  const [showTokenInput, setShowTokenInput] = useState(false);
  const [testSuccessMessage, setTestSuccessMessage] = useState<string | null>(null);

  const loadGitHubStatus = async () => {
    setLoading(true);
    try {
      const data = await getGitHubConfig();
      setConfig(data);
      if (data.masked_token) {
        setInputToken("");
      }
    } catch (err) {
      addToast(
        err instanceof Error ? err.message : "Falha ao consultar status do GitHub.",
        "error"
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGitHubStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleTestToken = async () => {
    if (!inputToken) {
      addToast("Insira um token PAT para testar.", "warning");
      return;
    }
    setTesting(true);
    setTestSuccessMessage(null);
    try {
      const res = await testGitHubToken(inputToken);
      if (res.valid && res.user) {
        setTestSuccessMessage(`✅ Conexão válida com @${res.user.login} (${res.user.name || "Usuário GitHub"})!`);
        addToast(`Token verificado com sucesso para @${res.user.login}.`, "success");
      } else {
        addToast(`Falha ao validar token: ${res.error || "Token rejeitado pela API do GitHub."}`, "error");
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Erro ao testar token.", "error");
    } finally {
      setTesting(false);
    }
  };

  const handleSaveToken = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setTestSuccessMessage(null);
    try {
      const updated = await updateGitHubConfig(inputToken);
      setConfig(updated);
      setShowTokenInput(false);
      setInputToken("");
      addToast(
        updated.status === "authenticated"
          ? "Token do GitHub atualizado e autenticado com sucesso!"
          : "Configuração de token salva.",
        "success"
      );
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao salvar token.", "error");
    } finally {
      setSaving(false);
    }
  };

  const statusBadge = () => {
    if (!config) return null;
    switch (config.status) {
      case "authenticated":
        return <span className="badge-tag green">✅ Conectado</span>;
      case "error":
        return <span className="badge-tag red">❌ Erro de Autenticação</span>;
      default:
        return <span className="badge-tag yellow">⚠️ Não Configurado</span>;
    }
  };

  return (
    <div className="panel-box">
      <div className="panel-header">
        <div className="flex items-center gap-2">
          <span className="text-xl">🐙</span>
          <div>
            <h3 className="m-0 text-base font-semibold">Conta & Conexão GitHub</h3>
            <p className="text-xs text-muted m-0">
              Autenticação da API do GitHub para criação de PRs, leitura de Issues e status de CI/CD.
            </p>
          </div>
        </div>
        <div>{statusBadge()}</div>
      </div>

      {loading ? (
        <p className="text-xs text-muted mt-3">Verificando status do GitHub...</p>
      ) : (
        <div className="mt-4">
          {config?.user ? (
            <div className="p-4 rounded-lg mb-4 flex items-start gap-4" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
              {config.user.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={config.user.avatar_url}
                  alt={config.user.login}
                  className="w-14 h-14 rounded-full border border-border"
                  style={{ width: "56px", height: "56px", borderRadius: "50%", objectFit: "cover" }}
                />
              ) : (
                <div className="w-14 h-14 rounded-full flex items-center justify-center bg-gray-700 text-xl">
                  🐙
                </div>
              )}

              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="text-base font-semibold m-0">{config.user.name || config.user.login}</h4>
                    <a
                      href={config.user.html_url || `https://github.com/${config.user.login}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs font-mono text-blue-400 hover:underline"
                    >
                      @{config.user.login} ↗
                    </a>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-muted">Fonte do Token: </span>
                    <strong className="text-xs font-mono">
                      {config.token_source === "settings"
                        ? ".env / Settings"
                        : config.token_source === "gh_cli"
                        ? "gh CLI Keyring"
                        : "Nenhuma"}
                    </strong>
                  </div>
                </div>

                {config.user.bio && <p className="text-xs text-muted mt-2 mb-2">{config.user.bio}</p>}

                <div className="flex items-center gap-4 mt-3 text-xs">
                  <div>
                    <span className="text-muted">Repositórios Públicos: </span>
                    <strong>{config.user.public_repos ?? 0}</strong>
                  </div>
                  {config.user.email && (
                    <div>
                      <span className="text-muted">E-mail: </span>
                      <strong className="font-mono">{config.user.email}</strong>
                    </div>
                  )}
                  {config.masked_token && (
                    <div>
                      <span className="text-muted">Token: </span>
                      <code className="font-mono bg-black/20 px-1 py-0.5 rounded">{config.masked_token}</code>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="p-3 rounded-lg mb-4 text-xs text-muted" style={{ background: "var(--bg-secondary)", border: "1px dashed var(--border)" }}>
              {config?.error || "Nenhum token do GitHub ativo. Cadastre um Personal Access Token abaixo."}
            </div>
          )}

          {!showTokenInput && config?.status === "authenticated" ? (
            <div className="flex justify-between items-center mt-2">
              <span className="text-xs text-muted">
                O token ativo é utilizado para integrar o IDE e o Agente com repositórios GitHub.
              </span>
              <button
                type="button"
                className="btn-secondary-sm"
                onClick={() => setShowTokenInput(true)}
              >
                ✏️ Alterar Token PAT
              </button>
            </div>
          ) : (
            <form onSubmit={handleSaveToken} className="config-form mt-2">
              <div className="form-group">
                <div className="flex justify-between items-center mb-1">
                  <label htmlFor="github-token-input">GitHub Personal Access Token (PAT)</label>
                  <a
                    href="https://github.com/settings/tokens/new?scopes=repo,read:user,user:email,workflow&description=NovaAI Studio+IDE"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:underline"
                  >
                    🔑 Gerar Novo Token no GitHub (Scopes: repo, user, workflow) ↗
                  </a>
                </div>
                <input
                  id="github-token-input"
                  type="password"
                  className="input-text font-mono"
                  value={inputToken}
                  onChange={(e) => setInputToken(e.target.value)}
                  placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                />
              </div>

              {testSuccessMessage && (
                <div className="p-2 mb-3 rounded text-xs" style={{ background: "rgba(16, 185, 129, 0.15)", border: "1px solid rgba(16, 185, 129, 0.4)", color: "#10b981" }}>
                  {testSuccessMessage}
                </div>
              )}

              <div className="flex justify-between items-center mt-3">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleTestToken}
                  disabled={testing || !inputToken}
                >
                  {testing ? "Testando..." : "🔍 Testar Conexão"}
                </button>

                <div className="flex gap-2">
                  {showTokenInput && (
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        setShowTokenInput(false);
                        setInputToken("");
                      }}
                    >
                      Cancelar
                    </button>
                  )}
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={saving}
                  >
                    {saving ? "Salvar..." : "💾 Salvar Token no .env"}
                  </button>
                </div>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
