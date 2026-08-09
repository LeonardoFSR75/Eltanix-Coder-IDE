"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

export function RunCommandCard({ tool, content, data, ok }: ToolCardProps) {
  const command = String(data.command ?? "");
  const exitCode = data.exit_code as number | null | undefined;
  const durationMs = data.duration_ms as number | undefined;
  const timedOut = Boolean(data.timed_out);

  const metaParts: string[] = [];
  if (typeof exitCode === "number") metaParts.push(`saída ${exitCode}`);
  if (timedOut) metaParts.push("tempo esgotado");
  if (typeof durationMs === "number") metaParts.push(`${durationMs}ms`);

  const failed = timedOut || (typeof exitCode === "number" && exitCode !== 0);

  return (
    <ToolCardShell
      icon="💻"
      title={command || "executar comando"}
      meta={metaParts.join(" · ")}
      riskLevel={riskLevelForTool(tool)}
      ok={ok && !failed}
      defaultOpen={failed}
    >
      <pre className="tool-card-pre tool-card-terminal">{content}</pre>
    </ToolCardShell>
  );
}
