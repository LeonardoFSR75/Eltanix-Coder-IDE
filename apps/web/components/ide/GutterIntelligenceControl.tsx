"use client";

/**
 * Botão da barra do editor que liga/desliga as camadas de gutter intelligence
 * (Onda 1.5). A preferência é lembrada por navegador (localStorage).
 */

import { useEffect, useRef, useState } from "react";
import type { GutterLayers } from "@/lib/use-gutter-intelligence";

const ITEMS: { key: keyof GutterLayers; label: string; hint: string }[] = [
  { key: "blame", label: "Blame", hint: "autoria e idade de cada linha na margem" },
  { key: "coverage", label: "Cobertura", hint: "linhas cobertas / descobertas pelos testes" },
  { key: "cve", label: "CVEs", hint: "dependências vulneráveis no manifesto" },
];

export function GutterIntelligenceControl({
  layers,
  onChange,
}: {
  layers: GutterLayers;
  onChange: (next: GutterLayers) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const activeCount = ITEMS.filter((it) => layers[it.key]).length;

  return (
    <div className="gutter-int-control" ref={rootRef}>
      <button
        type="button"
        className={`theme-btn ${activeCount > 0 ? "active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="Gutter intelligence (blame · cobertura · CVEs)"
        style={{ padding: "4px 6px", display: "inline-flex", alignItems: "center", gap: 4 }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="9" y1="3" x2="9" y2="21" />
          <line x1="6" y1="7" x2="6" y2="7" />
          <line x1="6" y1="12" x2="6" y2="12" />
          <line x1="6" y1="17" x2="6" y2="17" />
        </svg>
        {activeCount > 0 && <span className="gutter-int-badge">{activeCount}</span>}
      </button>

      {open && (
        <div className="gutter-int-menu" role="menu">
          {ITEMS.map((it) => (
            <label key={it.key} className="gutter-int-item">
              <input
                type="checkbox"
                checked={layers[it.key]}
                onChange={(e) => onChange({ ...layers, [it.key]: e.target.checked })}
              />
              <span className="gutter-int-item-label">{it.label}</span>
              <span className="gutter-int-item-hint">{it.hint}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
