"use client";

import { useState } from "react";
import {
  confirmDiscoveredModels,
  discoverProviderModels,
  type CatalogModel,
  type DiscoveredModelCandidate,
  type DiscoverResponse,
} from "@/lib/api/providers";

const SUPPORTED_PROVIDERS = ["ollama", "databricks", "anthropic", "openai", "groq"] as const;
const CAPABILITY_OPTIONS = ["chat", "tools", "vision", "prompt_cache", "embedding"] as const;

interface CandidateEdit {
  id: string;
  context_window: number;
  capabilities: string[];
}

function editsFromCandidate(candidate: DiscoveredModelCandidate): CandidateEdit {
  return {
    id: candidate.suggested_id,
    context_window: candidate.context_window,
    capabilities: candidate.capabilities,
  };
}

interface ModelDiscoveryProps {
  onModelsAdded: (models: CatalogModel[]) => void;
  onStatus: (message: string) => void;
}

export function ModelDiscovery({ onModelsAdded, onStatus }: ModelDiscoveryProps) {
  const [discovering, setDiscovering] = useState<string | null>(null);
  const [result, setResult] = useState<DiscoverResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [edits, setEdits] = useState<Record<string, CandidateEdit>>({});
  const [confirming, setConfirming] = useState(false);

  const handleDiscover = async (provider: string) => {
    setDiscovering(provider);
    try {
      const data = await discoverProviderModels(provider);
      setResult(data);
      setSelected(new Set(data.new.map((c) => c.suggested_id)));
      setEdits(Object.fromEntries(data.new.map((c) => [c.suggested_id, editsFromCandidate(c)])));
    } catch (err) {
      onStatus(`Erro ao detectar modelos de ${provider}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setDiscovering(null);
    }
  };

  const toggleSelected = (suggestedId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(suggestedId)) next.delete(suggestedId);
      else next.add(suggestedId);
      return next;
    });
  };

  const updateEdit = (suggestedId: string, patch: Partial<CandidateEdit>) => {
    setEdits((prev) => ({ ...prev, [suggestedId]: { ...prev[suggestedId], ...patch } }));
  };

  const toggleCapability = (suggestedId: string, capability: string) => {
    setEdits((prev) => {
      const current = prev[suggestedId];
      const has = current.capabilities.includes(capability);
      return {
        ...prev,
        [suggestedId]: {
          ...current,
          capabilities: has
            ? current.capabilities.filter((c) => c !== capability)
            : [...current.capabilities, capability],
        },
      };
    });
  };

  const cancel = () => {
    setResult(null);
    setSelected(new Set());
    setEdits({});
  };

  const confirm = async () => {
    if (!result) return;
    const chosen = result.new.filter((c) => selected.has(c.suggested_id));
    if (chosen.length === 0) return;

    setConfirming(true);
    try {
      const models = chosen.map((candidate) => {
        const edit = edits[candidate.suggested_id];
        return {
          id: edit.id,
          model: candidate.model,
          deployment: candidate.deployment,
          endpoint: candidate.endpoint,
          mode: candidate.mode,
          context_window: edit.context_window,
          tags: candidate.tags,
          capabilities: edit.capabilities,
        };
      });
      const data = await confirmDiscoveredModels(result.provider, models);
      onModelsAdded(data.models);
      onStatus(`${data.added.length} modelo(s) adicionado(s) ao catálogo: ${data.added.join(", ")}`);
      cancel();
    } catch (err) {
      onStatus(`Erro ao adicionar modelos: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="label">Detectar modelos:</span>
        {SUPPORTED_PROVIDERS.map((provider) => (
          <button
            key={provider}
            type="button"
            className="theme-btn"
            disabled={discovering !== null}
            onClick={() => void handleDiscover(provider)}
          >
            {discovering === provider ? "detectando..." : provider}
          </button>
        ))}
      </div>

      {result && (
        <div style={{ marginTop: 16 }}>
          {result.error && (
            <div className="panel-error" style={{ marginBottom: 12 }}>
              {result.provider}: {result.error}
            </div>
          )}

          {!result.error && result.new.length === 0 && (
            <div className="hint">
              Nenhum modelo novo em {result.provider}
              {result.already_cataloged.length > 0 &&
                ` — os ${result.already_cataloged.length} encontrados já estão no catálogo.`}
              .
            </div>
          )}

          {result.new.length > 0 && (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th />
                      <th>Id no catálogo</th>
                      <th className="num">Janela</th>
                      <th>Capacidades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.new.map((candidate) => {
                      const edit = edits[candidate.suggested_id];
                      if (!edit) return null;
                      const isChecked = selected.has(candidate.suggested_id);
                      return (
                        <tr key={candidate.suggested_id}>
                          <td>
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => toggleSelected(candidate.suggested_id)}
                            />
                          </td>
                          <td>
                            <input
                              className="studio-input"
                              value={edit.id}
                              onChange={(e) =>
                                updateEdit(candidate.suggested_id, { id: e.target.value })
                              }
                              disabled={!isChecked}
                            />
                          </td>
                          <td className="num">
                            <input
                              type="number"
                              className="studio-input"
                              style={{ width: 90 }}
                              value={edit.context_window}
                              min={1}
                              onChange={(e) =>
                                updateEdit(candidate.suggested_id, {
                                  context_window: Number(e.target.value),
                                })
                              }
                              disabled={!isChecked}
                            />
                            {candidate.estimated_fields.includes("context_window") && (
                              <span className="hint" title="Estimado — o provedor não informa a janela real.">
                                {" "}
                                (estimado)
                              </span>
                            )}
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                              {CAPABILITY_OPTIONS.map((cap) => (
                                <label key={cap} style={{ fontSize: 11.5, display: "flex", gap: 4, alignItems: "center" }}>
                                  <input
                                    type="checkbox"
                                    checked={edit.capabilities.includes(cap)}
                                    disabled={!isChecked}
                                    onChange={() => toggleCapability(candidate.suggested_id, cap)}
                                  />
                                  {cap}
                                </label>
                              ))}
                            </div>
                            {candidate.estimated_fields.includes("capabilities") && (
                              <span className="hint" title="Estimado por heurística de nome — confira antes de salvar.">
                                (estimado)
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button
                  type="button"
                  className="theme-btn"
                  disabled={confirming || selected.size === 0}
                  onClick={() => void confirm()}
                >
                  {confirming ? "adicionando..." : `Adicionar ${selected.size} selecionado(s)`}
                </button>
                <button type="button" className="theme-btn" disabled={confirming} onClick={cancel}>
                  Cancelar
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
