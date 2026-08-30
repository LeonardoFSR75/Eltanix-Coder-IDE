/**
 * Predição do próximo edit / "tab to jump" (Onda 1.2, ADR 0015) — fala com
 * `POST /api/context/next-edit`.
 *
 * READ-only: o backend nunca escreve. O edit vira texto no editor só no
 * segundo `Tab` (o primeiro pula o cursor até o trecho). `found: false` e toda
 * falha voltam como `204` → `null` aqui, e o editor não arma a regra de `Tab`.
 * O desfecho (accepted/rejected/ignored) usa `reportCompletionOutcome` de
 * `completions.ts` com `kind: "next_edit"`.
 */

import { postOrNull } from "@/lib/client";

export interface RecentEdit {
  path: string;
  diff: string;
}

export interface NextEditRequest {
  project: string;
  path: string;
  file_content: string;
  cursor_line: number;
  recent_edits: RecentEdit[];
  language?: string | null;
}

export interface PredictedEdit {
  path: string;
  start_line: number;
  end_line: number;
  old_text: string;
  new_text: string;
  diff: string;
  jump_lines: number;
}

export interface NextEditResult {
  found: true;
  suggestion_id: string;
  edit: PredictedEdit;
  model: string;
  latency_ms: number;
}

export async function requestNextEdit(
  req: NextEditRequest,
  signal?: AbortSignal,
): Promise<NextEditResult | null> {
  return postOrNull<NextEditResult>("/api/context/next-edit", req, signal);
}
