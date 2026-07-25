"use client";

import { useCallback, useEffect, useState } from "react";
import { get } from "@/lib/client";

interface Entry {
  path: string;
  name: string;
  is_dir: boolean;
  size_bytes: number;
  language: string | null;
}

interface TreeResponse {
  root: string;
  entries: Entry[];
  truncated: boolean;
}

/**
 * Árvore de arquivos com expansão sob demanda.
 *
 * Carregar o repositório inteiro de uma vez travaria o browser em qualquer
 * projeto real — um nível por vez mantém a resposta pequena e o primeiro
 * render imediato.
 */
export function FileTree({
  onOpen,
  activePath,
}: {
  onOpen: (path: string) => void;
  activePath: string | null;
}) {
  const [levels, setLevels] = useState<Record<string, Entry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (subpath: string) => {
    setLoading((prev) => new Set(prev).add(subpath));
    try {
      const data = await get<TreeResponse>(
        `/api/workspace/tree?subpath=${encodeURIComponent(subpath)}`,
      );
      setLevels((prev) => ({ ...prev, [subpath]: data.entries }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading((prev) => {
        const next = new Set(prev);
        next.delete(subpath);
        return next;
      });
    }
  }, []);

  useEffect(() => {
    void load(".");
  }, [load]);

  const toggle = (entry: Entry) => {
    if (!entry.is_dir) {
      onOpen(entry.path);
      return;
    }
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(entry.path)) {
        next.delete(entry.path);
      } else {
        next.add(entry.path);
        if (!levels[entry.path]) void load(entry.path);
      }
      return next;
    });
  };

  const renderLevel = (subpath: string, depth: number) => {
    const entries = levels[subpath];
    if (!entries) return null;

    return entries.map((entry) => (
      <div key={entry.path}>
        <button
          type="button"
          className={`tree-row${activePath === entry.path ? " active" : ""}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => toggle(entry)}
          title={entry.path}
        >
          <span className="tree-icon">
            {entry.is_dir ? (expanded.has(entry.path) ? "▾" : "▸") : "·"}
          </span>
          <span className="tree-name">{entry.name}</span>
        </button>
        {entry.is_dir && expanded.has(entry.path) && (
          <>
            {loading.has(entry.path) && (
              <div className="tree-hint" style={{ paddingLeft: 22 + depth * 14 }}>
                carregando…
              </div>
            )}
            {renderLevel(entry.path, depth + 1)}
          </>
        )}
      </div>
    ));
  };

  if (error) {
    return <div className="tree-hint">{error}</div>;
  }

  return (
    <div className="tree">
      {loading.has(".") && !levels["."] && <div className="tree-hint">carregando…</div>}
      {renderLevel(".", 0)}
    </div>
  );
}
