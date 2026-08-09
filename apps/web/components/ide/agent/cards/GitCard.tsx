"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

const ICON: Record<string, string> = {
  git_status: "🌿",
  git_diff: "🔀",
  git_commit: "📌",
  open_pull_request: "🐙",
};

const LABEL: Record<string, string> = {
  git_status: "git status",
  git_diff: "git diff",
  git_commit: "commit",
  open_pull_request: "abrir PR",
};

const TITLE: Record<string, (data: Record<string, unknown>) => string> = {
  git_status: (d) => `git status${d.branch ? ` · ${d.branch}` : ""}`,
  git_diff: () => "git diff",
  git_commit: (d) => `commit ${String(d.sha ?? "").slice(0, 8)}`,
  open_pull_request: (d) => `PR #${d.number ?? "?"}`,
};

export function GitCard({ tool, content, data, ok }: ToolCardProps) {
  const icon = ICON[tool] ?? "🌿";
  const riskLevel = riskLevelForTool(tool);

  // Em falha, ToolResult.failure() zera `data` — sem sha/número/branch, os
  // títulos acima ficavam truncados e vazios (ex.: "commit "). O erro em si
  // já está em `content`, então abrimos o card por padrão.
  if (!ok) {
    return (
      <ToolCardShell
        icon={icon}
        title={`${LABEL[tool] ?? tool} — falhou`}
        riskLevel={riskLevel}
        ok={false}
        defaultOpen
      >
        <pre className="tool-card-pre">{content}</pre>
      </ToolCardShell>
    );
  }

  const title = TITLE[tool]?.(data) ?? tool;
  const meta =
    tool === "git_status" && typeof data.files === "number" ? `${data.files} arquivo(s)` : undefined;

  return (
    <ToolCardShell icon={icon} title={title} meta={meta} riskLevel={riskLevel} ok={ok}>
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}
