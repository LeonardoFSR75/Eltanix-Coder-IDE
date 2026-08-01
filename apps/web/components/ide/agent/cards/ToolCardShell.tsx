"use client";

import { useState } from "react";

export interface ToolCardShellProps {
  icon: string;
  title: string;
  meta?: string;
  ok?: boolean;
  defaultOpen?: boolean;
  // Cards com conteúdo que precisa de mais altura (o DiffEditor do Monaco,
  // por exemplo) passam uma classe própria em vez de herdar o max-height
  // pensado para saída de texto.
  bodyClassName?: string;
  children?: React.ReactNode;
}

// Casca comum a todo card de tool-call: cabeçalho sempre visível (ícone,
// título, resumo curto) + corpo colapsável para o detalhe (diff, stdout,
// hits de busca...). Ferramentas sem card dedicado caem no fallback em
// ToolCallCard, que usa a mesma casca com o texto truncado de antes.
export function ToolCardShell({
  icon,
  title,
  meta,
  ok = true,
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
        {meta && <span className="tool-card-meta">{meta}</span>}
        {hasBody && <span className="tool-card-chevron">{open ? "▾" : "▸"}</span>}
      </button>
      {open && hasBody && (
        <div className={`tool-card-body${bodyClassName ? ` ${bodyClassName}` : ""}`}>{children}</div>
      )}
    </div>
  );
}
