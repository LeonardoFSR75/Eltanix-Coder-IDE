"use client";

/**
 * Revisão hunk a hunk de uma edição inline (Cmd+K nível 2, Onda 1.3).
 *
 * Cada bloco de mudança contíguo é um checkbox; ao aplicar, só os marcados
 * vão para o backend (`POST /api/agent/inline-edit/apply`), que reconstrói o
 * arquivo e grava. Todos começam marcados.
 */

import { useState } from "react";
import type { InlineEditHunk } from "@/lib/api/inlineEdit";

function line(prefix: string, raw: string) {
  return prefix + raw.replace(/\n$/, "");
}

export function InlineEditHunkReview({
  hunks,
  busy = false,
  onApply,
  onCancel,
}: {
  hunks: InlineEditHunk[];
  busy?: boolean;
  onApply: (acceptedIds: string[]) => void;
  onCancel: () => void;
}) {
  const [accepted, setAccepted] = useState<Set<string>>(
    () => new Set(hunks.map((h) => h.id)),
  );

  const toggle = (id: string) =>
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="hunk-review">
      <div className="hunk-review-head">
        ✨ Edição inline — {hunks.length} blocos. Marque os que quer aplicar; o resto fica como
        está.
      </div>
      <div className="hunk-review-list">
        {hunks.map((h) => (
          <label
            key={h.id}
            className={`hunk-item ${accepted.has(h.id) ? "on" : "off"}`}
          >
            <input
              type="checkbox"
              checked={accepted.has(h.id)}
              disabled={busy}
              onChange={() => toggle(h.id)}
            />
            <pre className="hunk-diff">
              {h.context_before.map((l, k) => (
                <span key={`cb${k}`} className="hunk-ln ctx">
                  {line("  ", l)}
                </span>
              ))}
              {h.before_lines.map((l, k) => (
                <span key={`b${k}`} className="hunk-ln del">
                  {line("- ", l)}
                </span>
              ))}
              {h.after_lines.map((l, k) => (
                <span key={`a${k}`} className="hunk-ln add">
                  {line("+ ", l)}
                </span>
              ))}
              {h.context_after.map((l, k) => (
                <span key={`ca${k}`} className="hunk-ln ctx">
                  {line("  ", l)}
                </span>
              ))}
            </pre>
          </label>
        ))}
      </div>
      <div className="hunk-review-actions">
        <button
          type="button"
          className="theme-btn primary"
          disabled={busy}
          onClick={() => onApply([...accepted])}
        >
          {busy ? "aplicando…" : `Aplicar ${accepted.size} de ${hunks.length}`}
        </button>
        <button type="button" className="theme-btn" disabled={busy} onClick={onCancel}>
          cancelar
        </button>
      </div>
    </div>
  );
}
