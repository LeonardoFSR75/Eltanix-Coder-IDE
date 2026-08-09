"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

export function ReadFileCard({ tool, content, data, ok }: ToolCardProps) {
  const path = String(data.path ?? "");
  const lines = data.lines as number | undefined;

  // Em falha, ToolResult.failure() zera `data` — sem `path`, o título "ler "
  // ficava vazio embora o erro (com o caminho) já esteja em `content`.
  if (!ok || !path) {
    return (
      <ToolCardShell icon="📄" title="ler arquivo — falhou" riskLevel={riskLevelForTool(tool)} ok={false} defaultOpen>
        <pre className="tool-card-pre">{content}</pre>
      </ToolCardShell>
    );
  }

  return (
    <ToolCardShell
      icon="📄"
      title={`ler ${path}`}
      meta={lines ? `${lines} linhas` : undefined}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
    >
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}

export function ListFilesCard({ tool, content, data, ok }: ToolCardProps) {
  const entries = (data.entries as Array<{ path: string; is_dir: boolean }> | undefined) ?? [];

  return (
    <ToolCardShell
      icon="📁"
      title="listar arquivos"
      meta={`${entries.length} itens`}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
    >
      <pre className="tool-card-pre">{content}</pre>
    </ToolCardShell>
  );
}
