"use client";

import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

interface GraphNode {
  path: string;
  symbol: string | null;
  kind: string;
}

export function GraphCard({ content, data, ok }: ToolCardProps) {
  const node = data.node as GraphNode | undefined;
  const contains = (data.contains as GraphNode[] | undefined) ?? [];
  const containedBy = data.contained_by as GraphNode | null | undefined;
  const imports = (data.imports as string[] | undefined) ?? [];
  const importedBy = (data.imported_by as string[] | undefined) ?? [];

  return (
    <ToolCardShell
      icon="🕸️"
      title={node ? `grafo · ${node.symbol ?? node.path}` : "code graph"}
      ok={ok}
    >
      {node ? (
        <ul className="tool-card-list">
          {containedBy && <li>contido por: {containedBy.symbol}</li>}
          {contains.map((c) => (
            <li key={`${c.path}-${c.symbol}`}>contém: {c.symbol} ({c.kind})</li>
          ))}
          {imports.map((p) => (
            <li key={`imports-${p}`}>importa: {p}</li>
          ))}
          {importedBy.map((p) => (
            <li key={`imported-by-${p}`}>importado por: {p}</li>
          ))}
        </ul>
      ) : (
        <pre className="tool-card-pre">{content}</pre>
      )}
    </ToolCardShell>
  );
}
