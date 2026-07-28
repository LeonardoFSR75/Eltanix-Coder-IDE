"use client";

import React, { useState } from "react";
import { post } from "@/lib/client";
import { formatMs } from "@/lib/format";
import type { CatalogModel, CatalogProfile, ProviderCheck } from "@/lib/api";

interface ProviderStudioProps {
  initialHealth: { healthy: number; total: number; providers: ProviderCheck[] };
  initialCatalog: { models: CatalogModel[]; profiles: CatalogProfile[] };
}

export function ProviderStudio({ initialHealth, initialCatalog }: ProviderStudioProps) {
  const [activeTab, setActiveTab] = useState<"catalog" | "credentials" | "profiles">("catalog");
  const [healthData, setHealthData] = useState(initialHealth);
  const [profiles, setProfiles] = useState(initialCatalog.profiles);
  const [resettingModel, setResettingModel] = useState<string | null>(null);
  const [settingDefault, setSettingDefault] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const handleSetDefaultProfile = async (profileName: string) => {
    setSettingDefault(profileName);
    try {
      const data = await post<{ profiles: CatalogProfile[] }>("/api/providers/default-profile", {
        profile: profileName,
      });
      setProfiles(data.profiles);
      setStatusMsg(`Perfil "${profileName}" agora é o padrão (usado quando o modelo pedido é "auto").`);
    } catch (err) {
      setStatusMsg(`Erro ao trocar o perfil padrão: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSettingDefault(null);
    }
  };

  // Configurações Locais de Credenciais simuladas/editáveis
  const [credentials, setCredentials] = useState({
    ollamaUrl: "http://localhost:5405",
    azureEndpoint: "https://my-resource.openai.azure.com",
    azureKey: "••••••••••••••••",
    databricksHost: "https://adb-12345678.azuredatabricks.net",
    databricksToken: "dapi••••••••••••••••",
    openaiKey: "sk-proj-••••••••••••••••",
    anthropicKey: "sk-ant-••••••••••••••••",
    githubToken: "ghp_••••••••••••••••",
  });

  const checks = new Map(healthData.providers.map((p) => [p.model, p]));

  const handleResetCircuit = async (modelId: string) => {
    setResettingModel(modelId);
    try {
      await post(`/api/providers/${encodeURIComponent(modelId)}/reset`, {});
      setStatusMsg(`Circuito do modelo ${modelId} foi resetado com sucesso!`);
      // Atualiza estado local
      setHealthData((prev) => ({
        ...prev,
        providers: prev.providers.map((p) =>
          p.model === modelId ? { ...p, circuit_open: false, ok: true } : p,
        ),
      }));
    } catch (err) {
      setStatusMsg(`Erro ao resetar circuito: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setResettingModel(null);
    }
  };

  return (
    <div className="provider-studio">
      <div className="studio-tabs">
        <button
          type="button"
          className={`studio-tab ${activeTab === "catalog" ? "active" : ""}`}
          onClick={() => setActiveTab("catalog")}
        >
          📊 Catálogo & Saúde ({initialHealth.healthy}/{initialCatalog.models.length})
        </button>
        <button
          type="button"
          className={`studio-tab ${activeTab === "credentials" ? "active" : ""}`}
          onClick={() => setActiveTab("credentials")}
        >
          ⚙️ Credenciais & Endpoints
        </button>
        <button
          type="button"
          className={`studio-tab ${activeTab === "profiles" ? "active" : ""}`}
          onClick={() => setActiveTab("profiles")}
        >
          🔀 Perfis de Roteamento
        </button>
      </div>

      {statusMsg && (
        <div className="tree-hint ok-hint" style={{ margin: "12px 0", color: "var(--accent-emerald)" }}>
          {statusMsg}
        </div>
      )}

      {activeTab === "catalog" && (
        <div className="studio-section">
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16, marginBottom: 24 }}>
            <div className="card">
              <div className="label">Provedores Online</div>
              <div className="value" style={{ color: "var(--accent-emerald)" }}>
                {healthData.healthy} / {healthData.total}
              </div>
              <div className="hint">circuitos normais</div>
            </div>
            <div className="card">
              <div className="label">Modelos Cadastrados</div>
              <div className="value">{initialCatalog.models.length}</div>
              <div className="hint">catalogo ativo</div>
            </div>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Modelo</th>
                  <th>Estado</th>
                  <th className="num">Janela</th>
                  <th className="num">Sonda (ms)</th>
                  <th className="num">$/1M in</th>
                  <th className="num">$/1M out</th>
                  <th>Ação</th>
                </tr>
              </thead>
              <tbody>
                {initialCatalog.models.map((m) => {
                  const check = checks.get(m.id);
                  const isCircuitOpen = check?.circuit_open;

                  return (
                    <tr key={m.id}>
                      <td>
                        <code>{m.id}</code>
                        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{m.provider}</div>
                      </td>
                      <td>
                        {!m.enabled ? (
                          <span className="pill">desligado</span>
                        ) : !m.available ? (
                          <span className="pill warn">sem credencial</span>
                        ) : isCircuitOpen ? (
                          <span className="pill bad">circuito aberto ({check.cooldown_remaining_s}s)</span>
                        ) : check?.ok ? (
                          <span className="pill ok">online</span>
                        ) : (
                          <span className="pill bad">offline</span>
                        )}
                      </td>
                      <td className="num">{(m.context_window / 1000).toFixed(0)}k</td>
                      <td className="num">{formatMs(check?.probe_latency_ms)}</td>
                      <td className="num">{m.price?.input ?? "—"}</td>
                      <td className="num">{m.price?.output ?? "—"}</td>
                      <td>
                        {isCircuitOpen && (
                          <button
                            type="button"
                            className="theme-btn"
                            disabled={resettingModel === m.id}
                            onClick={() => void handleResetCircuit(m.id)}
                          >
                            {resettingModel === m.id ? "resetando..." : "Resetar Circuito"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "credentials" && (
        <div className="studio-section">
          <div className="credentials-form grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 20 }}>
            <div className="card">
              <h3>🦙 Ollama Local</h3>
              <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
                URL Base
              </label>
              <input
                className="studio-input"
                value={credentials.ollamaUrl}
                onChange={(e) => setCredentials({ ...credentials, ollamaUrl: e.target.value })}
              />
              <div className="hint" style={{ marginTop: 8 }}>Porta padrão Docker: 5405 / Local: 11434</div>
            </div>

            <div className="card">
              <h3>☁️ Azure AI Foundry / OpenAI</h3>
              <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
                Endpoint Azure
              </label>
              <input
                className="studio-input"
                value={credentials.azureEndpoint}
                onChange={(e) => setCredentials({ ...credentials, azureEndpoint: e.target.value })}
              />
              <label style={{ display: "block", fontSize: 12, margin: "12px 0 4px", color: "var(--text-dim)" }}>
                API Key Azure
              </label>
              <input
                type="password"
                className="studio-input"
                value={credentials.azureKey}
                onChange={(e) => setCredentials({ ...credentials, azureKey: e.target.value })}
              />
            </div>

            <div className="card">
              <h3>🧱 Databricks Vector Search</h3>
              <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
                Host Workspace
              </label>
              <input
                className="studio-input"
                value={credentials.databricksHost}
                onChange={(e) => setCredentials({ ...credentials, databricksHost: e.target.value })}
              />
              <label style={{ display: "block", fontSize: 12, margin: "12px 0 4px", color: "var(--text-dim)" }}>
                Token PAT
              </label>
              <input
                type="password"
                className="studio-input"
                value={credentials.databricksToken}
                onChange={(e) => setCredentials({ ...credentials, databricksToken: e.target.value })}
              />
            </div>

            <div className="card">
              <h3>🔑 OpenAI & Anthropic</h3>
              <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
                OpenAI Key
              </label>
              <input
                type="password"
                className="studio-input"
                value={credentials.openaiKey}
                onChange={(e) => setCredentials({ ...credentials, openaiKey: e.target.value })}
              />
              <label style={{ display: "block", fontSize: 12, margin: "12px 0 4px", color: "var(--text-dim)" }}>
                Anthropic Key
              </label>
              <input
                type="password"
                className="studio-input"
                value={credentials.anthropicKey}
                onChange={(e) => setCredentials({ ...credentials, anthropicKey: e.target.value })}
              />
            </div>
          </div>
        </div>
      )}

      {activeTab === "profiles" && (
        <div className="studio-section">
          <div className="hint" style={{ marginBottom: 12 }}>
            O perfil padrão é usado quando o cliente pede o modelo <code>&quot;auto&quot;</code> (ou não
            especifica nenhum). A troca vale na hora e é salva em <code>config/routes.yaml</code>.
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Perfil</th>
                  <th>Estratégia de Roteamento</th>
                  <th>Cadeia de Fallback Dinâmica</th>
                  <th>Ação</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.name}>
                    <td>
                      <code>{p.name}</code> {p.is_default && <span className="pill ok">padrão</span>}
                    </td>
                    <td>
                      <span className="pill">{p.strategy}</span>
                    </td>
                    <td style={{ whiteSpace: "normal" }}>
                      {p.models.length > 0 ? (
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                          {p.models.map((m, idx) => (
                            <React.Fragment key={m}>
                              {idx > 0 && <span style={{ color: "var(--accent)" }}>➔</span>}
                              <code className="kbd-badge">{m}</code>
                            </React.Fragment>
                          ))}
                        </div>
                      ) : (
                        <em>vazio</em>
                      )}
                    </td>
                    <td>
                      {!p.is_default && (
                        <button
                          type="button"
                          className="theme-btn"
                          disabled={settingDefault === p.name}
                          onClick={() => void handleSetDefaultProfile(p.name)}
                        >
                          {settingDefault === p.name ? "aplicando..." : "Tornar padrão"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
