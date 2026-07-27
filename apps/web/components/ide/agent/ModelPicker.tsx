"use client";

/**
 * Seletor de perfil de roteamento, para a sessão do agente.
 *
 * Busca de `/api/providers` — dado real (`config/routes.yaml`), não uma lista
 * inventada. Nunca importa de `lib/api.ts`: aquele módulo é só para Server
 * Components e guarda a chave da API num jeito que não pode vazar pro bundle
 * do cliente; aqui a busca passa pelo proxy `/api/gateway` via `lib/client.ts`,
 * igual a todo o resto do IDE.
 */

import { useEffect, useState } from "react";
import { get } from "@/lib/client";

interface CatalogProfile {
  name: string;
  strategy: string;
  models: string[];
  weights: Record<string, number>;
  is_default: boolean;
}

let cache: Promise<CatalogProfile[]> | null = null;

function loadProfiles(): Promise<CatalogProfile[]> {
  if (!cache) {
    cache = get<{ profiles: CatalogProfile[] }>("/api/providers")
      .then((r) => r.profiles.filter((p) => p.name !== "embedding"))
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
  const [perfis, setPerfis] = useState<CatalogProfile[] | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let cancelado = false;
    loadProfiles()
      .then((p) => {
        if (!cancelado) setPerfis(p);
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
    <select
      className="model-picker"
      value={value ?? ""}
      disabled={disabled || !perfis}
      onChange={(e) => onChange(e.target.value || null)}
      title="Perfil de roteamento — vazio usa o padrão do modo"
    >
      <option value="">automático (por modo)</option>
      {(perfis ?? []).map((p) => (
        <option key={p.name} value={p.name}>
          {p.name}
          {p.is_default ? " · padrão" : ""}
        </option>
      ))}
    </select>
  );
}
