"use client";

import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

export function ReadFileCard({ content, data, ok }: ToolCardProps) {
  const path = String(data.path ?? "");
  const lines = data.lines as number | undefined;

  return (
    <ToolCardShell
      icon="📄"
      title={`ler ${path}`}
      meta={lines ? `${lines} linhas` : undefined}
      ok={ok}
    >
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}

export function ListFilesCard({ content, data, ok }: ToolCardProps) {
  const entries = (data.entries as Array<{ path: string; is_dir: boolean }> | undefined) ?? [];

  return (
    <ToolCardShell icon="📁" title="listar arquivos" meta={`${entries.length} itens`} ok={ok}>
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}
