"use client";

import { useState } from "react";
import type { CatalogModel } from "@/lib/api/providers";

const STRATEGIES = ["priority", "cost", "latency", "score"] as const;
const WEIGHT_KEYS = ["health", "cost", "latency", "success_rate", "context_fit"] as const;

export interface ProfileFormValue {
  name: string;
  strategy: string;
  models: string[];
  weights: Record<string, number>;
}

interface ProfileEditorProps {
  mode: "create" | "edit";
  initial: ProfileFormValue;
  availableModels: CatalogModel[];
  saving: boolean;
  onCancel: () => void;
  onSave: (value: ProfileFormValue) => void;
}

export function ProfileEditor({
  mode,
  initial,
  availableModels,
  saving,
  onCancel,
  onSave,
}: ProfileEditorProps) {
  const [name, setName] = useState(initial.name);
  const [strategy, setStrategy] = useState(initial.strategy);
  const [models, setModels] = useState<string[]>(initial.models);
  const [weights, setWeights] = useState<Record<string, number>>(initial.weights);
  const [modelToAdd, setModelToAdd] = useState("");
  const [error, setError] = useState<string | null>(null);

  const addModel = () => {
    if (!modelToAdd || models.includes(modelToAdd)) return;
    setModels((prev) => [...prev, modelToAdd]);
    setModelToAdd("");
  };

  const removeModel = (id: string) => setModels((prev) => prev.filter((m) => m !== id));

  const moveModel = (idx: number, dir: -1 | 1) => {
    setModels((prev) => {
      const alvo = idx + dir;
      if (alvo < 0 || alvo >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[alvo]] = [next[alvo], next[idx]];
      return next;
    });
  };

  const submit = () => {
    if (mode === "create" && !/^[a-z][a-z0-9_-]{0,31}$/.test(name)) {
      setError(
        "Nome inválido: letras minúsculas, números, \"-\" ou \"_\", começando com letra (até 32 caracteres).",
      );
      return;
    }
    if (models.length === 0) {
      setError("Escolha pelo menos um modelo para a cadeia de fallback.");
      return;
    }
    setError(null);
    onSave({ name, strategy, models, weights });
  };

  return (
    <tr className="profile-editor-row">
      <td colSpan={4}>
        <div className="card" style={{ padding: 16 }}>
          {mode === "create" && (
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
                Nome do perfil
              </label>
              <input
                className="studio-input"
                value={name}
                onChange={(e) => setName(e.target.value.trim())}
                placeholder="ex.: minha-rota"
                autoFocus
              />
            </div>
          )}

          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
              Estratégia
            </label>
            <select
              className="studio-input"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
              Cadeia de fallback (a ordem é a ordem de tentativa)
            </label>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
              {models.map((m, idx) => (
                <div key={m} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--text-dim)", fontSize: 12, width: 20 }}>{idx + 1}.</span>
                  <code className="kbd-badge" style={{ flex: 1 }}>
                    {m}
                  </code>
                  <button
                    type="button"
                    className="theme-btn"
                    disabled={idx === 0}
                    onClick={() => moveModel(idx, -1)}
                    title="Subir na ordem de tentativa"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="theme-btn"
                    disabled={idx === models.length - 1}
                    onClick={() => moveModel(idx, 1)}
                    title="Descer na ordem de tentativa"
                  >
                    ↓
                  </button>
                  <button type="button" className="theme-btn" onClick={() => removeModel(m)}>
                    remover
                  </button>
                </div>
              ))}
              {models.length === 0 && <em style={{ fontSize: 12 }}>nenhum modelo ainda</em>}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <select
                className="studio-input"
                value={modelToAdd}
                onChange={(e) => setModelToAdd(e.target.value)}
              >
                <option value="">selecionar modelo…</option>
                {availableModels
                  .filter((m) => !models.includes(m.id))
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
                    </option>
                  ))}
              </select>
              <button type="button" className="theme-btn" disabled={!modelToAdd} onClick={addModel}>
                + adicionar
              </button>
            </div>
          </div>

          {strategy === "score" && (
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "var(--text-dim)" }}>
                Pesos (só entram em jogo na estratégia &quot;score&quot;)
              </label>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                  gap: 8,
                }}
              >
                {WEIGHT_KEYS.map((k) => (
                  <div key={k}>
                    <label style={{ display: "block", fontSize: 11, color: "var(--text-dim)" }}>{k}</label>
                    <input
                      type="number"
                      min={0}
                      step={0.05}
                      className="studio-input"
                      value={weights[k] ?? 0}
                      onChange={(e) =>
                        setWeights((prev) => ({ ...prev, [k]: Number(e.target.value) }))
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div className="panel-error" style={{ marginBottom: 8 }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="theme-btn" disabled={saving} onClick={submit}>
              {saving ? "salvando..." : "Salvar"}
            </button>
            <button type="button" className="theme-btn" disabled={saving} onClick={onCancel}>
              Cancelar
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}
