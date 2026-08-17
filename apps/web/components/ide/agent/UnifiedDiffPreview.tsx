"use client";

import { useState } from "react";

interface UnifiedDiffPreviewProps {
  diff: string;
  defaultOpen?: boolean;
}

type DiffLineKind = "add" | "del" | "hunk" | "meta" | "ctx";

function classifyLine(line: string): DiffLineKind {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  if (line.startsWith("@@")) return "hunk";
  return "ctx";
}

export function UnifiedDiffPreview({ diff, defaultOpen = false }: UnifiedDiffPreviewProps) {
  const [open, setOpen] = useState(defaultOpen);
  const lines = diff.split("\n");

  return (
    <div className="approval-diff-preview">
      <button
        type="button"
        className="approval-diff-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "▾" : "▸"} {open ? "Ocultar diff" : "Ver diff"}
      </button>
      {open && (
        <pre className="approval-diff-body">
          {lines.map((line, index) => (
            <div key={index} className={`approval-diff-line ${classifyLine(line)}`}>
              {line || " "}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
