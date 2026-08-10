"use client";

/**
 * Seletor de modelo / perfil de roteamento para a atividade do agente.
 *
 * Busca de `/api/providers` (perfis de `config/routes.yaml` e modelos ativos).
 */

import { useEffect, useState } from "react";
import { getCatalog, type CatalogModel, type CatalogProfile } from "@/lib/api/providers";

interface ProvidersResponse {
  profiles: CatalogProfile[];
  models: CatalogModel[];
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
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;
    getCatalog()
      .then((r) => {
        if (!isMounted) return;
        const allModels = r.models || [];
        const allProfiles = (r.profiles || []).filter((p) => p.name !== "embedding");
        setData({
          profiles: allProfiles,
          models: allModels,
        });
        setLoading(false);
      })
      .catch((err) => {
        console.warn("Falha ao carregar catálogo de modelos:", err);
        if (isMounted) {
          setData({ profiles: [], models: [] });
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const hasSelectedInProfiles = data?.profiles.some((p) => p.name === value);
  const hasSelectedInModels = data?.models.some((m) => m.id === value);
  const isCustomSelection = value && !hasSelectedInProfiles && !hasSelectedInModels;

  return (
    <div className="model-picker-container" title="Selecione o modelo ou perfil ativo para a atividade">
      <span className="model-picker-icon">🤖</span>
      <select
        className="model-picker-select"
        value={value ?? ""}
        disabled={disabled || loading}
        onChange={(e) => onChange(e.target.value || null)}
      >
        {loading ? (
          <>
            <option value="">Gemini 3.6 Flash (High) ⚡</option>
            <option value="gemini-1.5-pro">Gemini 1.5 Pro</option>
          </>
        ) : (
          <>
            <option value="">⚡ Gemini 3.6 Flash (High)</option>

            {isCustomSelection && (
              <option value={value}>
                [Ativo] {value}
              </option>
            )}

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
              <optgroup label="── Modelos do Catálogo ──">
                {data.models.map((m) => (
                  <option key={`m-${m.id}`} value={m.id}>
                    [{m.provider}] {m.id} {m.available !== false ? "✓" : "○"}
                  </option>
                ))}
              </optgroup>
            )}
          </>
        )}
      </select>
    </div>
  );
}
