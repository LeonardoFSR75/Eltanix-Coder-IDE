"use client";

import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

export function CodeReviewCard({ content, data, ok }: ToolCardProps) {
  const verdict = data.verdict === "approved" ? "Aprovado" : "Precisa de revisão";
  const icon = data.verdict === "approved" ? "✅" : "🔎";

  return (
    <ToolCardShell icon={icon} title="revisão de código" meta={verdict} ok={ok} defaultOpen>
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}
