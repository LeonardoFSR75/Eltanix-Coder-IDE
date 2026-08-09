"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

export function ExplorerCard({ tool, content, data, ok }: ToolCardProps) {
  const cycles = (data.cycles as string[][] | undefined) ?? [];
  const orphans = (data.orphans as string[] | undefined) ?? [];
  const riskLevel = riskLevelForTool(tool);

  if (tool === "find_circular_imports") {
    return (
      <ToolCardShell
        icon="🔁"
        title="dependência circular"
        meta={`${cycles.length} ciclo(s)`}
        riskLevel={riskLevel}
        ok={ok}
      >
        {cycles.length > 0 ? (
          <ul className="tool-card-list">
            {cycles.map((cycle, i) => (
              <li key={i}>{cycle.join(" → ")}</li>
            ))}
          </ul>
        ) : (
          <pre className="tool-card-pre">{content}</pre>
        )}
      </ToolCardShell>
    );
  }

  return (
    <ToolCardShell
      icon="🕳️"
      title="módulos órfãos"
      meta={`${orphans.length} candidato(s)`}
      riskLevel={riskLevel}
      ok={ok}
    >
      {orphans.length > 0 ? (
        <ul className="tool-card-list">
          {orphans.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      ) : (
        <pre className="tool-card-pre">{content}</pre>
      )}
    </ToolCardShell>
  );
}
