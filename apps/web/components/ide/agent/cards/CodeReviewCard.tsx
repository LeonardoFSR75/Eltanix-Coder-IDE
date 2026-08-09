"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

export function CodeReviewCard({ tool, content, data, ok }: ToolCardProps) {
  const verdict = data.verdict === "approved" ? "Aprovado" : "Precisa de revisão";
  const icon = data.verdict === "approved" ? "✅" : "🔎";

  return (
    <ToolCardShell
      icon={icon}
      title="revisão de código"
      meta={verdict}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
      defaultOpen
    >
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}
