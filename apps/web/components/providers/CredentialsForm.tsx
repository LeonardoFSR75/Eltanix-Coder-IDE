"use client";

import { useState } from "react";
import { put } from "@/lib/client";
import type { CredentialsView } from "@/lib/api";

type FieldKey =
  | "ollama_base_url"
  | "azure_api_base"
  | "azure_api_key"
  | "databricks_host"
  | "databricks_token"
  | "openai_api_key"
  | "anthropic_api_key"
  | "github_token";

interface CredentialsFormProps {
  initial: CredentialsView;
  onSaved: (updated: CredentialsView) => void;
  onError: (message: string) => void;
}

function buildValues(view: CredentialsView): Record<FieldKey, string> {
  return {
    ollama_base_url: view.ollama_base_url.value ?? "",
    azure_api_base: view.azure_api_base.value ?? "",
    azure_api_key: "",
    databricks_host: view.databricks_host.value ?? "",
    databricks_token: "",
    openai_api_key: "",
    anthropic_api_key: "",
    github_token: "",
  };
}

const labelStyle = { display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" } as const;
const labelStyleSpaced = { ...labelStyle, margin: "12px 0 4px" } as const;

export function CredentialsForm({ initial, onSaved, onError }: CredentialsFormProps) {
  const [current, setCurrent] = useState(initial);
  const [values, setValues] = useState<Record<FieldKey, string>>(() => buildValues(initial));
  const [touched, setTouched] = useState<Set<FieldKey>>(new Set());
  const [saving, setSaving] = useState(false);

  const setField = (key: FieldKey, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setTouched((prev) => new Set(prev).add(key));
  };

  const hasChanges = touched.size > 0;

  const secretPlaceholder = (key: FieldKey) => {
    const field = current[key];
    return field.configured ? `configurado (${field.masked}) — digite para trocar` : "não configurado";
  };

  const submit = async () => {
    if (!hasChanges) return;
    setSaving(true);
    try {
      const payload: Partial<Record<FieldKey, string>> = {};
      for (const key of touched) payload[key] = values[key];
      const data = await put<{ credentials: CredentialsView }>("/api/providers/credentials", payload);
      setCurrent(data.credentials);
      setValues(buildValues(data.credentials));
      setTouched(new Set());
      onSaved(data.credentials);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="hint" style={{ marginBottom: 12 }}>
        Chaves nunca voltam para a tela depois de salvas — só um indicador de que estão
        configuradas e os últimos 4 caracteres, para você reconhecer qual é qual. Aplica na
        hora (sem restart) e grava no <code>.env</code> da raiz.
      </div>
      <div
        className="credentials-form grid"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 20 }}
      >
        <div className="card">
          <h3>🦙 Ollama Local</h3>
          <label style={labelStyle}>URL Base</label>
          <input
            className="studio-input"
            value={values.ollama_base_url}
            onChange={(e) => setField("ollama_base_url", e.target.value)}
          />
          <div className="hint" style={{ marginTop: 8 }}>Porta padrão Docker: 5405 / Local: 11434</div>
        </div>

        <div className="card">
          <h3>☁️ Azure AI Foundry</h3>
          <label style={labelStyle}>Endpoint Azure</label>
          <input
            className="studio-input"
            value={values.azure_api_base}
            placeholder="https://meu-recurso.openai.azure.com"
            onChange={(e) => setField("azure_api_base", e.target.value)}
          />
          <label style={labelStyleSpaced}>API Key Azure</label>
          <input
            type="password"
            className="studio-input"
            value={values.azure_api_key}
            placeholder={secretPlaceholder("azure_api_key")}
            onChange={(e) => setField("azure_api_key", e.target.value)}
          />
        </div>

        <div className="card">
          <h3>🧱 Databricks Model Serving</h3>
          <label style={labelStyle}>Host Workspace</label>
          <input
            className="studio-input"
            value={values.databricks_host}
            placeholder="https://adb-12345678.azuredatabricks.net"
            onChange={(e) => setField("databricks_host", e.target.value)}
          />
          <label style={labelStyleSpaced}>Token PAT</label>
          <input
            type="password"
            className="studio-input"
            value={values.databricks_token}
            placeholder={secretPlaceholder("databricks_token")}
            onChange={(e) => setField("databricks_token", e.target.value)}
          />
        </div>

        <div className="card">
          <h3>🔑 OpenAI & Anthropic</h3>
          <label style={labelStyle}>OpenAI Key</label>
          <input
            type="password"
            className="studio-input"
            value={values.openai_api_key}
            placeholder={secretPlaceholder("openai_api_key")}
            onChange={(e) => setField("openai_api_key", e.target.value)}
          />
          <label style={labelStyleSpaced}>Anthropic Key</label>
          <input
            type="password"
            className="studio-input"
            value={values.anthropic_api_key}
            placeholder={secretPlaceholder("anthropic_api_key")}
            onChange={(e) => setField("anthropic_api_key", e.target.value)}
          />
        </div>

        <div className="card">
          <h3>🐙 GitHub</h3>
          <label style={labelStyle}>Token (PAT)</label>
          <input
            type="password"
            className="studio-input"
            value={values.github_token}
            placeholder={secretPlaceholder("github_token")}
            onChange={(e) => setField("github_token", e.target.value)}
          />
          <div className="hint" style={{ marginTop: 8 }}>
            Se vazio, o backend tenta obter o token do <code>gh auth token</code>.
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <button type="button" className="theme-btn" disabled={!hasChanges || saving} onClick={() => void submit()}>
          {saving ? "salvando..." : "Salvar credenciais"}
        </button>
      </div>
    </div>
  );
}
