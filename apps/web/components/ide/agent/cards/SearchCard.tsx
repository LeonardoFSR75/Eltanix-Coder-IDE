"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

interface Hit {
  path: string;
  citation: string;
  score?: number;
}

export function SearchCard({ tool, content, data, ok }: ToolCardProps) {
  const hits = (data.hits as Hit[] | undefined) ?? [];

  return (
    <ToolCardShell
      icon="🔍"
      title="buscar no código"
      meta={`${hits.length} trecho(s)`}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
    >
      {hits.length > 0 ? (
        <ul className="tool-card-list">
          {hits.map((hit, i) => (
            <li key={i}>{hit.citation || hit.path}</li>
          ))}
        </ul>
      ) : (
        <pre className="tool-card-pre">{content}</pre>
      )}
    </ToolCardShell>
  );
}
