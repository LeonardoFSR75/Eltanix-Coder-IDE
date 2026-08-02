"use client";

/**
 * Seletor de modelo / perfil de roteamento para a atividade do agente.
 *
 * Busca de `/api/providers` (perfis de `config/routes.yaml` e modelos ativos).
 */

import { useEffect, useState } from "react";
import { get } from "@/lib/client";

interface CatalogModel {
  id: string;
  provider: string;
  available: boolean;
}

interface CatalogProfile {
  name: string;
  strategy: string;
  models: string[];
  is_default: boolean;
}

interface ProvidersResponse {
  profiles: CatalogProfile[];
  models: CatalogModel[];
}

let cache: Promise<ProvidersResponse> | null = null;

function loadProvidersData(): Promise<ProvidersResponse> {
  if (!cache) {
    cache = get<ProvidersResponse>("/api/providers")
      .then((r) => ({
        profiles: (r.profiles || []).filter((p) => p.name !== "embedding"),
        models: (r.models || []).filter((m) => m.available),
      }))
      .catch((err) => {
        cache = null;
        throw err;
      });
  }
  return cache;
}

export function ModelPicker({
  value,
  onChange,
  disabled,
}: {
  value: string | null;
  onChange: (profile: string | null) => void;
  disabled?: boolean;
}) {
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let cancelado = false;
    loadProvidersData()
      .then((res) => {
        if (!cancelado) setData(res);
      })
      .catch(() => {
        if (!cancelado) setErro(true);
      });
    return () => {
      cancelado = true;
    };
  }, []);

  if (erro) return null;

  return (
    <div className="model-picker-container" title="Selecione o modelo ou perfil para a atividade">
      <span className="model-picker-icon">🤖</span>
      <select
        className="model-picker-select"
        value={value ?? ""}
        disabled={disabled || !data}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">⚡ Auto (Roteamento por modo)</option>

        {data?.profiles && data.profiles.length > 0 && (
          <optgroup label="── Perfis de Roteamento ──">
            {data.profiles.map((p) => (
              <option key={`p-${p.name}`} value={p.name}>
                Perfil: {p.name} {p.is_default ? "★ (padrão)" : ""}
              </option>
            ))}
          </optgroup>
        )}

        {data?.models && data.models.length > 0 && (
          <optgroup label="── Modelos Específicos ──">
            {data.models.map((m) => (
              <option key={`m-${m.id}`} value={m.id}>
                [{m.provider}] {m.id}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </div>
  );
}
