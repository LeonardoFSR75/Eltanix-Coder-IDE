"use client";

import { useIde } from "@/lib/ide-store";
import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

// `browser_action` cobre navigate/click/type/screenshot/content num tool
// só (mesmo padrão de run_command para shell) — o card exibe o screenshot,
// url/título, e alertas de erros de console/página capturados pelo Playwright.
export function BrowserCard({ tool, content, data, ok }: ToolCardProps) {
  const { openFile } = useIde();
  const image = typeof data.image_base64 === "string" ? data.image_base64 : null;
  const url = typeof data.url === "string" ? data.url : undefined;
  const title = typeof data.title === "string" ? data.title : undefined;
  const consoleErrors = Array.isArray(data.console_errors) ? (data.console_errors as string[]) : [];
  const pageErrors = Array.isArray(data.page_errors) ? (data.page_errors as string[]) : [];
  const hasErrors = consoleErrors.length > 0 || pageErrors.length > 0;

  const abrirNoEditor = () => {
    const alvo = url || "http://localhost:5000";
    openFile(`browser:${alvo}`);
  };

  return (
    <ToolCardShell
      icon="🌐"
      title={content.length > 90 ? `${content.slice(0, 90)}…` : content}
      meta={url}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
      defaultOpen={Boolean(image || hasErrors)}
    >
      {image && (
        <div className="browser-card-screenshot-container" style={{ position: "relative" }}>
          <div
            className="browser-card-screenshot"
            onClick={abrirNoEditor}
            style={{ cursor: "pointer" }}
            title="Clique para abrir e interagir no painel central do editor"
          >
            <img src={`data:image/png;base64,${image}`} alt={title || url || "screenshot"} />
          </div>
          <button
            type="button"
            className="browser-card-open-btn"
            onClick={abrirNoEditor}
            title="Abrir no editor central para visualizar em tamanho grande e interagir"
          >
            <span>🔍 Abrir no Navegador Central (Grande) ↗</span>
          </button>
        </div>
      )}
      {hasErrors && (
        <div className="p-2 my-2 rounded bg-amber-950/40 border border-amber-800/60 text-xs text-amber-200 font-mono space-y-1">
          <div className="font-semibold text-amber-400">⚠️ Erros no Console/Página:</div>
          {pageErrors.map((err, i) => (
            <div key={`p-${i}`} className="text-red-400">
              [PAGE ERROR] {err}
            </div>
          ))}
          {consoleErrors.map((err, i) => (
            <div key={`c-${i}`}>{err}</div>
          ))}
        </div>
      )}
      {!image && !hasErrors && <pre className="tool-card-pre">{content}</pre>}
    </ToolCardShell>
  );
}
