"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

interface BlameHunk {
  start_line: number;
  end_line: number;
  sha: string;
  author: string;
  date: string;
  message: string;
}

interface CoChangeEntry {
  path: string;
  count: number;
}

export function BlameCard({ tool, content, data, ok }: ToolCardProps) {
  const hunks = (data.hunks as BlameHunk[] | undefined) ?? [];
  const coChanged = (data.co_changed as CoChangeEntry[] | undefined) ?? [];

  return (
    <ToolCardShell
      icon="🕘"
      title="histórico do código"
      meta={hunks.length ? `${hunks.length} trecho(s)` : undefined}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
    >
      {hunks.length > 0 ? (
        <ul className="tool-card-list">
          {hunks.map((h) => (
            <li key={`${h.sha}-${h.start_line}`}>
              L{h.start_line}-{h.end_line} · {h.sha} · {h.author} — {h.message}
            </li>
          ))}
        </ul>
      ) : (
        <pre className="tool-card-pre">{content}</pre>
      )}
      {coChanged.length > 0 && (
        <ul className="tool-card-list">
          {coChanged.slice(0, 5).map((c) => (
            <li key={c.path}>muda junto: {c.path} ({c.count}x)</li>
          ))}
        </ul>
      )}
    </ToolCardShell>
  );
}
