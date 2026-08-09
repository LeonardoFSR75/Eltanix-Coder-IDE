"use client";

import { useState } from "react";

export interface ToolCardShellProps {
  icon: string;
  title: string;
  meta?: string;
  ok?: boolean;
  riskLevel?: "low" | "medium" | "high";
  defaultOpen?: boolean;
  bodyClassName?: string;
  children?: React.ReactNode;
}

// Espelha a RiskClass declarada em cada ferramenta nativa (ver
// agent/tools/*.py) — READ/WRITE/EXEC → low/medium/high. É estático porque,
// para as ferramentas nativas com card dedicado, o risco não depende dos
// argumentos da chamada, só do nome da tool.
const TOOL_RISK: Record<string, "low" | "medium" | "high"> = {
  read_file: "low",
  list_files: "low",
  search_code: "low",
  git_status: "low",
  git_diff: "low",
  code_history: "low",
  request_code_review: "low",
  code_graph: "low",
  find_circular_imports: "low",
  find_orphan_modules: "low",
  write_file: "medium",
  edit_file: "medium",
  git_commit: "medium",
  open_pull_request: "medium",
  run_command: "high",
  browser_action: "high",
};

export function riskLevelForTool(tool: string): "low" | "medium" | "high" | undefined {
  return TOOL_RISK[tool];
}

export function ToolCardShell({
  icon,
  title,
  meta,
  ok = true,
  riskLevel,
  defaultOpen = false,
  bodyClassName,
  children,
}: ToolCardShellProps) {
  const [open, setOpen] = useState(defaultOpen);
  const hasBody = Boolean(children);

  return (
    <div className={`tool-card${ok ? "" : " fail"}`}>
      <button
        type="button"
        className="tool-card-header"
        onClick={() => hasBody && setOpen((v) => !v)}
        aria-expanded={open}
        disabled={!hasBody}
      >
        <span className="tool-card-icon">{icon}</span>
        <span className="tool-card-title">{title}</span>
        {riskLevel && (
          <span
            className={`tool-card-risk-badge ${riskLevel}`}
            title={`Nível de risco: ${riskLevel.toUpperCase()}`}
          >
            {riskLevel}
          </span>
        )}
        {meta && <span className="tool-card-meta">{meta}</span>}
        {hasBody && <span className="tool-card-chevron">{open ? "▾" : "▸"}</span>}
      </button>
      {open && hasBody && (
        <div className={`tool-card-body${bodyClassName ? ` ${bodyClassName}` : ""}`}>{children}</div>
      )}
    </div>
  );
}
