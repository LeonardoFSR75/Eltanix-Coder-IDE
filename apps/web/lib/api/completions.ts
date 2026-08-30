/**
 * Autocompletar inline / ghost text (Onda 1.1, ADR 0014) — fala com
 * `POST /api/context/completions`.
 *
 * READ-only: o backend nunca escreve arquivo. A sugestão vira texto no editor
 * só quando o usuário aperta `Tab` (nativo do Monaco). Toda falha do recurso
 * (kill switch, modelo fora, timeout) volta como `204` → `null` aqui, e o
 * provider simplesmente não mostra nada. Ghost text falha em silêncio.
 */

import { post, postOrNull } from "@/lib/client";

export interface CompletionRequest {
  project: string;
  path: string;
  prefix: string;
  suffix: string;
  language?: string | null;
}

export interface CompletionResult {
  completion: string;
  suggestion_id: string;
  model: string;
  cached: boolean;
  latency_ms: number;
}

export async function requestCompletion(
  req: CompletionRequest,
  signal?: AbortSignal,
): Promise<CompletionResult | null> {
  return postOrNull<CompletionResult>("/api/context/completions", req, signal);
}

export type CompletionOutcomeKind = "accepted" | "rejected" | "ignored";

export interface CompletionOutcome {
  suggestion_id: string;
  outcome: CompletionOutcomeKind;
  project?: string | null;
  language?: string | null;
  model?: string | null;
  shown_ms?: number | null;
  latency_ms?: number | null;
  chars_suggested?: number;
  chars_accepted?: number;
}

/** Telemetria de aceitação — o número que diz se o autocompletar presta.
 * Best-effort: nunca deixa um erro de rede vazar para o editor. */
export function reportCompletionOutcome(outcome: CompletionOutcome): void {
  void post("/api/context/completions/outcome", outcome).catch(() => {});
}
