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

  const riskBadgeColor =
    riskLevel === "high"
      ? "bg-red-950 text-red-400 border-red-800"
      : riskLevel === "medium"
      ? "bg-amber-950 text-amber-400 border-amber-800"
      : "bg-slate-900 text-slate-400 border-slate-700";

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
            className={`text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase ${riskBadgeColor}`}
            title={`Nível de Risco: ${riskLevel.toUpperCase()}`}
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
