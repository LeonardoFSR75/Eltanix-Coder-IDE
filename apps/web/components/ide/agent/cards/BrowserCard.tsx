"use client";

import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

// `browser_action` cobre navigate/click/type/screenshot/content num tool
// só (mesmo padrão de run_command para shell) — o card não sabe qual ação
// foi essa além do que `data` deixa transparecer (imagem = screenshot, url+
// título = navigate, texto = content); o resumo em `content` (montado no
// backend) cobre os demais casos sem precisar de mais estado.
export function BrowserCard({ content, data, ok }: ToolCardProps) {
  const image = typeof data.image_base64 === "string" ? data.image_base64 : null;
  const url = typeof data.url === "string" ? data.url : undefined;
  const title = typeof data.title === "string" ? data.title : undefined;

  return (
    <ToolCardShell
      icon="🌐"
      title={content.length > 90 ? `${content.slice(0, 90)}…` : content}
      meta={url}
      ok={ok}
      defaultOpen={Boolean(image)}
    >
      {image ? (
        <div className="browser-card-screenshot">
          <img src={`data:image/png;base64,${image}`} alt={title || url || "screenshot"} />
        </div>
      ) : (
        <pre className="tool-card-pre">{content}</pre>
      )}
    </ToolCardShell>
  );
}
