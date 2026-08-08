"use client";

import React, { useState, useEffect } from "react";
import { useToast } from "@/components/Toast";
import {
  getGitConfig,
  updateGitConfig,
  type GitUserConfig,
} from "@/lib/api/git-config";

interface GitUserConfigCardProps {
  currentProject?: string | null;
  onConfigUpdated?: (config: GitUserConfig) => void;
}

export function GitUserConfigCard({
  currentProject,
  onConfigUpdated,
}: GitUserConfigCardProps) {
  const { addToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [scope, setScope] = useState<"global" | "local">("global");

  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("main");
  const [autocrlf, setAutocrlf] = useState("input");
  const [gpgSign, setGpgSign] = useState(false);
  const [signingKey, setSigningKey] = useState("");

  const [sshKeys, setSshKeys] = useState<string[]>([]);
  const [localName, setLocalName] = useState<string | null>(null);
  const [localEmail, setLocalEmail] = useState<string | null>(null);

  const loadConfig = async () => {
    setLoading(true);
    try {
      const cfg = await getGitConfig(currentProject ?? undefined);
      if (scope === "local" && (cfg.local_user_name || cfg.local_user_email)) {
        setUserName(cfg.local_user_name || cfg.user_name || "");
        setUserEmail(cfg.local_user_email || cfg.user_email || "");
      } else {
        setUserName(cfg.user_name || "");
        setUserEmail(cfg.user_email || "");
      }
      setDefaultBranch(cfg.default_branch || "main");
      setAutocrlf(cfg.autocrlf || "input");
      setGpgSign(cfg.gpg_sign || false);
      setSigningKey(cfg.signing_key || "");
      setSshKeys(cfg.ssh_keys || []);
      setLocalName(cfg.local_user_name);
      setLocalEmail(cfg.local_user_email);
      onConfigUpdated?.(cfg);
    } catch (err) {
      addToast(
        err instanceof Error ? err.message : "Falha ao carregar configurações do Git.",
        "error"
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject, scope]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await updateGitConfig({
        user_name: userName,
        user_email: userEmail,
        default_branch: defaultBranch,
        autocrlf: autocrlf,
        gpg_sign: gpgSign,
        signing_key: signingKey,
        scope: scope,
        project: currentProject ?? undefined,
      });
      addToast(`Configuração Git (${scope}) atualizada com sucesso!`, "success");
      setLocalName(updated.local_user_name);
      setLocalEmail(updated.local_user_email);
      onConfigUpdated?.(updated);
    } catch (err) {
      addToast(
        err instanceof Error ? err.message : "Falha ao salvar configurações do Git.",
        "error"
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="panel-box">
      <div className="panel-header">
        <div className="flex items-center gap-2">
          <span className="text-xl">⚙️</span>
          <div>
            <h3 className="m-0 text-base font-semibold">Identidade & Assinatura Git</h3>
            <p className="text-xs text-muted m-0">
              Nome de autor, e-mail dos commits e opções de line endings do ambiente.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="tab-pill-selector">
            <button
              type="button"
              className={`btn-secondary-sm ${scope === "global" ? "active-tab" : ""}`}
              onClick={() => setScope("global")}
            >
              🌐 Global (~/.gitconfig)
            </button>
            <button
              type="button"
              className={`btn-secondary-sm ${scope === "local" ? "active-tab" : ""}`}
              onClick={() => setScope("local")}
              disabled={!currentProject}
              title={!currentProject ? "Selecione um projeto para editar a config local" : ""}
            >
              📁 Local ({currentProject || "Sem projeto"})
            </button>
          </div>
        </div>
      </div>

      {loading ? (
        <p className="text-xs text-muted">Carregando configurações Git...</p>
      ) : (
        <form onSubmit={handleSubmit} className="config-form mt-4">
          {scope === "local" && (localName || localEmail) && (
            <div className="info-banner mb-3 text-xs p-2 rounded" style={{ background: "rgba(59, 130, 246, 0.1)", border: "1px solid rgba(59, 130, 246, 0.3)", color: "var(--fg)" }}>
              ℹ️ Este projeto tem override local de autor: <strong>{localName || "—"}</strong> ({localEmail || "—"}).
            </div>
          )}

          <div className="grid grid-2 gap-4">
            <div className="form-group">
              <label htmlFor="git-user-name">Nome do Autor (user.name)</label>
              <input
                id="git-user-name"
                type="text"
                className="input-text"
                value={userName}
                onChange={(e) => setUserName(e.target.value)}
                placeholder="Ex: Seu Nome Completo"
              />
            </div>

            <div className="form-group">
              <label htmlFor="git-user-email">E-mail do Autor (user.email)</label>
              <input
                id="git-user-email"
                type="email"
                className="input-text"
                value={userEmail}
                onChange={(e) => setUserEmail(e.target.value)}
                placeholder="Ex: dev@exemplo.com"
              />
            </div>

            <div className="form-group">
              <label htmlFor="git-default-branch">Branch Padrão de Inicialização (init.defaultBranch)</label>
              <input
                id="git-default-branch"
                type="text"
                className="input-text font-mono"
                value={defaultBranch}
                onChange={(e) => setDefaultBranch(e.target.value)}
                placeholder="main"
              />
            </div>

            <div className="form-group">
              <label htmlFor="git-autocrlf">Tratamento de Quebras de Linha (core.autocrlf)</label>
              <select
                id="git-autocrlf"
                className="input-text"
                value={autocrlf}
                onChange={(e) => setAutocrlf(e.target.value)}
              >
                <option value="input">input (Recomendado para Linux/macOS ou repositórios cruzados)</option>
                <option value="true">true (Recomendado para Windows clássico)</option>
                <option value="false">false (Desativado / Manter exatamente como escrito)</option>
              </select>
            </div>
          </div>

          <div className="divider my-4" style={{ height: "1px", background: "var(--border)", opacity: 0.5 }} />

          <div className="grid grid-2 gap-4">
            <div className="form-group">
              <div className="flex items-center gap-2 mb-2">
                <input
                  id="git-gpg-sign"
                  type="checkbox"
                  checked={gpgSign}
                  onChange={(e) => setGpgSign(e.target.checked)}
                />
                <label htmlFor="git-gpg-sign" className="cursor-pointer font-medium text-sm">
                  🔒 Assinar commits por padrão (commit.gpgsign)
                </label>
              </div>
              <p className="text-xs text-muted">
                Ativa a verificação de commits assinados via chave GPG ou SSH.
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="git-signing-key">Chave de Assinatura (user.signingkey)</label>
              <input
                id="git-signing-key"
                type="text"
                className="input-text font-mono"
                value={signingKey}
                onChange={(e) => setSigningKey(e.target.value)}
                placeholder="Ex: 3AA5C34371567BD2 ou key.pub"
                disabled={!gpgSign}
              />
            </div>
          </div>

          <div className="mt-4 p-3 rounded-lg" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
            <div className="flex items-center justify-between">
              <div>
                <strong className="text-xs font-semibold">🔑 Status de Chaves SSH no Host:</strong>
                <div className="flex gap-2 mt-1">
                  {sshKeys.length > 0 ? (
                    sshKeys.map((key) => (
                      <span key={key} className="badge-tag green text-xs font-mono">
                        {key}
                      </span>
                    ))
                  ) : (
                    <span className="badge-tag red text-xs">Nenhuma chave SSH encontrada em ~/.ssh</span>
                  )}
                </div>
              </div>
              <span className="text-xs text-muted">
                {sshKeys.length > 0
                  ? "Pronto para autenticação SSH com GitHub / GitLab."
                  : "Crie uma chave via `ssh-keygen` para pushes via SSH."}
              </span>
            </div>
          </div>

          <div className="mt-4 flex justify-end">
            <button
              type="submit"
              className="btn-primary"
              disabled={saving}
            >
              {saving ? "Salvando..." : "💾 Salvar Configurações Git"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
