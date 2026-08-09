"use client";

import React, { useState } from "react";
import { formatMs } from "@/lib/format";
import { ProfileEditor, type ProfileFormValue } from "@/components/providers/ProfileEditor";
import { CredentialsForm } from "@/components/providers/CredentialsForm";
import { ModelDiscovery } from "@/components/providers/ModelDiscovery";
import {
  deleteProfile,
  saveProfile,
  setDefaultProfile,
  type CatalogModel,
  type CatalogProfile,
  type CredentialsView,
} from "@/lib/api/providers";
import { resetCircuit, type ProviderCheck } from "@/lib/api/health";

const NEW_PROFILE = "__new__";

interface ProviderStudioProps {
  initialHealth: { healthy: number; total: number; providers: ProviderCheck[] };
  initialCatalog: { models: CatalogModel[]; profiles: CatalogProfile[] };
  initialCredentials: CredentialsView;
}

export function ProviderStudio({ initialHealth, initialCatalog, initialCredentials }: ProviderStudioProps) {
  const [activeTab, setActiveTab] = useState<"catalog" | "credentials" | "profiles">("catalog");
  const [healthData, setHealthData] = useState(initialHealth);
  const [models, setModels] = useState(initialCatalog.models);
  const [profiles, setProfiles] = useState(initialCatalog.profiles);
  const [resettingModel, setResettingModel] = useState<string | null>(null);
  const [settingDefault, setSettingDefault] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [editingProfile, setEditingProfile] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState<string | null>(null);

  const handleSetDefaultProfile = async (profileName: string) => {
    setSettingDefault(profileName);
    try {
      const profiles = await setDefaultProfile(profileName);
      setProfiles(profiles);
      setStatusMsg(`Perfil "${profileName}" agora é o padrão (usado quando o modelo pedido é "auto").`);
    } catch (err) {
      setStatusMsg(`Erro ao trocar o perfil padrão: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSettingDefault(null);
    }
  };

  const handleSaveProfile = async (value: ProfileFormValue) => {
    setSavingProfile(true);
    try {
      const profiles = await saveProfile({
        name: value.name,
        strategy: value.strategy,
        models: value.models,
        weights: value.strategy === "score" ? value.weights : undefined,
      });
      setProfiles(profiles);
      setStatusMsg(`Perfil "${value.name}" salvo.`);
      setEditingProfile(null);
    } catch (err) {
      setStatusMsg(`Erro ao salvar o perfil: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSavingProfile(false);
    }
  };

  const handleDeleteProfile = async (profileName: string) => {
    if (!window.confirm(`Excluir o perfil "${profileName}"? Essa ação não tem volta.`)) return;
    setDeletingProfile(profileName);
    try {
      const profiles = await deleteProfile(profileName);
      setProfiles(profiles);
      setStatusMsg(`Perfil "${profileName}" excluído.`);
    } catch (err) {
      setStatusMsg(`Erro ao excluir o perfil: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setDeletingProfile(null);
    }
  };

  const [credentials, setCredentials] = useState(initialCredentials);

  const checks = new Map(healthData.providers.map((p) => [p.model, p]));

  const handleResetCircuit = async (modelId: string) => {
    setResettingModel(modelId);
    try {
      await resetCircuit(modelId);
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
          📊 Catálogo & Saúde ({initialHealth.healthy}/{models.length})
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
          <ModelDiscovery
            onModelsAdded={(updated) => setModels(updated)}
            onStatus={(message) => setStatusMsg(message)}
          />
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
              <div className="value">{models.length}</div>
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
                {models.map((m) => {
                  const check = checks.get(m.id);
                  const isCircuitOpen = check?.circuit_open;

                  return (
                    <tr key={m.id}>
                      <td>
                        <code>{m.id}</code>
                        <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{m.provider}</div>
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
          <CredentialsForm
            initial={credentials}
            onSaved={(updated) => {
              setCredentials(updated);
              setStatusMsg("Credenciais salvas — já valendo para a próxima chamada, sem restart.");
            }}
            onError={(message) => setStatusMsg(`Erro ao salvar credenciais: ${message}`)}
          />
        </div>
      )}

      {activeTab === "profiles" && (
        <div className="studio-section">
          <div className="hint" style={{ marginBottom: 12 }}>
            O perfil padrão é usado quando o cliente pede o modelo <code>&quot;auto&quot;</code> (ou não
            especifica nenhum). Estratégia, cadeia de fallback e pesos são salvos em{" "}
            <code>config/routes.yaml</code> na hora.
          </div>
          <div style={{ marginBottom: 12 }}>
            <button
              type="button"
              className="theme-btn"
              disabled={editingProfile !== null}
              onClick={() => setEditingProfile(NEW_PROFILE)}
            >
              + Novo perfil
            </button>
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
                {editingProfile === NEW_PROFILE && (
                  <ProfileEditor
                    mode="create"
                    initial={{ name: "", strategy: "priority", models: [], weights: {} }}
                    availableModels={models}
                    saving={savingProfile}
                    onCancel={() => setEditingProfile(null)}
                    onSave={(value) => void handleSaveProfile(value)}
                  />
                )}
                {profiles.map((p) =>
                  editingProfile === p.name ? (
                    <ProfileEditor
                      key={p.name}
                      mode="edit"
                      initial={{ name: p.name, strategy: p.strategy, models: p.models, weights: p.weights }}
                      availableModels={models}
                      saving={savingProfile}
                      onCancel={() => setEditingProfile(null)}
                      onSave={(value) => void handleSaveProfile(value)}
                    />
                  ) : (
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
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          {!p.is_default && (
                            <button
                              type="button"
                              className="theme-btn"
                              disabled={settingDefault === p.name || editingProfile !== null}
                              onClick={() => void handleSetDefaultProfile(p.name)}
                            >
                              {settingDefault === p.name ? "aplicando..." : "Tornar padrão"}
                            </button>
                          )}
                          <button
                            type="button"
                            className="theme-btn"
                            disabled={editingProfile !== null}
                            onClick={() => setEditingProfile(p.name)}
                          >
                            Editar
                          </button>
                          {!p.is_default && (
                            <button
                              type="button"
                              className="theme-btn"
                              disabled={editingProfile !== null || deletingProfile === p.name}
                              onClick={() => void handleDeleteProfile(p.name)}
                            >
                              {deletingProfile === p.name ? "excluindo..." : "Excluir"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
