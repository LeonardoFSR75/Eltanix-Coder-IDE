"use client";

import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

const ICON: Record<string, string> = {
  git_status: "🌿",
  git_diff: "🔀",
  git_commit: "📌",
  open_pull_request: "🐙",
};

const TITLE: Record<string, (data: Record<string, unknown>) => string> = {
  git_status: (d) => `git status${d.branch ? ` · ${d.branch}` : ""}`,
  git_diff: () => "git diff",
  git_commit: (d) => `commit ${String(d.sha ?? "").slice(0, 8)}`,
  open_pull_request: (d) => `PR #${d.number ?? "?"}`,
};

export function GitCard({ tool, content, data, ok }: ToolCardProps) {
  const title = TITLE[tool]?.(data) ?? tool;
  const icon = ICON[tool] ?? "🌿";
  const meta =
    tool === "git_status" && typeof data.files === "number" ? `${data.files} arquivo(s)` : undefined;

  return (
    <ToolCardShell icon={icon} title={title} meta={meta} ok={ok}>
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}
