"use client";

import { riskLevelForTool, ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

// O revisor (agent/review_common.py) responde com "VEREDITO: APROVADO/PRECISA_REVISAO"
// seguido de texto livre — o prompt pede um parágrafo só, mas modelos às vezes
// devolvem uma lista de qualquer forma. Em ambos os casos, quebrar em itens
// lê melhor num card do que um bloco de texto corrido.
function extractFindings(content: string): string[] {
  const semVeredito = content.replace(/^VEREDITO:\s*(APROVADO|PRECISA_REVISAO)\s*/i, "").trim();
  if (!semVeredito) return [];

  const linhas = semVeredito
    .split(/\r?\n/)
    .map((linha) => linha.replace(/^[-*•]\s*/, "").trim())
    .filter(Boolean);
  if (linhas.length > 1) return linhas;

  const sentencas = semVeredito
    .split(/(?<=[.!?])\s+(?=[A-ZÀ-Ú])/)
    .map((s) => s.trim())
    .filter((s) => s.length > 3);
  return sentencas.length > 0 ? sentencas : [semVeredito];
}

export function CodeReviewCard({ tool, content, data, ok }: ToolCardProps) {
  const aprovado = data.verdict === "approved";
  const verdict = aprovado ? "Aprovado" : "Precisa de revisão";
  const icon = aprovado ? "✅" : "🔎";
  const findings = extractFindings(content);

  return (
    <ToolCardShell
      icon={icon}
      title="revisão de código"
      meta={verdict}
      riskLevel={riskLevelForTool(tool)}
      ok={ok}
      defaultOpen
    >
      {findings.length > 0 ? (
        <ul className="tool-card-list code-review-findings">
          {findings.map((finding, i) => (
            <li key={i} className={aprovado ? "approved" : "needs-revision"}>
              <span className="code-review-finding-icon">{aprovado ? "✓" : "!"}</span>
              <span>{finding}</span>
            </li>
          ))}
        </ul>
      ) : (
        <pre className="tool-card-pre">{content}</pre>
      )}
    </ToolCardShell>
  );
}
