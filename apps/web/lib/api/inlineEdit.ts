/**
 * Edição inline (Fase 7 do upgrade do agente, estilo Cmd+K) — fala com
 * `POST /api/agent/inline-edit`. A partir da Onda 1.3 há a variante nível 2:
 * `POST /api/agent/inline-edit/stream` (a substituição chega em streaming) +
 * `POST /api/agent/inline-edit/apply` (grava só os hunks aceitos).
 *
 * Fora do ciclo de sessão do agente de propósito: uma seleção pontual no
 * editor não precisa de sessão/checkpoint completo, só de uma chamada
 * isolada de LLM sobre o trecho selecionado.
 */

import { post, streamEvents } from "@/lib/client";

export interface InlineEditRequest {
  project: string;
  path: string;
  selected_text: string;
  instruction: string;
  context_before?: string;
  context_after?: string;
}

/** Um bloco de mudança contíguo dentro da substituição — a unidade que o
 * usuário aceita ou rejeita no review nível 2. */
export interface InlineEditHunk {
  id: string;
  before_start: number;
  before_lines: string[];
  after_lines: string[];
  context_before: string[];
  context_after: string[];
}

export interface InlineEditResult {
  path: string;
  old_text: string;
  new_text: string;
  before: string;
  after: string;
  diff: string;
  changed_lines: number;
  hunks: InlineEditHunk[];
  // true quando a edição já foi escrita no arquivo (bateu numa regra de
  // auto-aprovação de `.eltanix/approval_policy.yaml`) — nesse caso o
  // frontend só recarrega o buffer, não chama writeFile de novo.
  applied: boolean;
  auto_approved_reason: string | null;
}

// `signal` deixa o editor abortar a chamada quando o usuário cancela o Cmd+K
// (Esc enquanto gera) — o backend cancela o `engine.complete()` ao ver a
// conexão cair, então tokens não são gastos por um resultado descartado.
export function requestInlineEdit(
  req: InlineEditRequest,
  signal?: AbortSignal,
): Promise<InlineEditResult> {
  return post<InlineEditResult>("/api/agent/inline-edit", req, signal);
}

/** Variante nível 2 (Onda 1.3): `onToken` recebe cada pedaço da substituição
 * conforme o modelo gera; a promise resolve com o `InlineEditResult` completo
 * (com `hunks`) do evento `done`, ou rejeita com o `detail` de um `error`. */
export async function streamInlineEdit(
  req: InlineEditRequest,
  handlers: { onToken?: (delta: string) => void },
  signal?: AbortSignal,
): Promise<InlineEditResult> {
  let result: InlineEditResult | null = null;
  let errorDetail: string | null = null;

  await streamEvents(
    "/api/agent/inline-edit/stream",
    req,
    (ev: unknown) => {
      const e = ev as { type?: string; delta?: string; detail?: string } & Partial<InlineEditResult>;
      if (e.type === "token" && typeof e.delta === "string") handlers.onToken?.(e.delta);
      else if (e.type === "done") result = e as unknown as InlineEditResult;
      else if (e.type === "error") errorDetail = e.detail ?? "Falha ao gerar a edição.";
    },
    signal,
  );

  if (errorDetail) throw new Error(errorDetail);
  if (!result) throw new Error("O streaming terminou sem um resultado.");
  return result;
}

export interface InlineEditApplyRequest {
  project: string;
  path: string;
  before: string;
  after: string;
  hunks: InlineEditHunk[];
  accepted_ids: string[];
}

export interface InlineEditApplyResult {
  applied: true;
  after: string;
  accepted: string[];
  changed_lines: number;
}

export function applyInlineEditHunks(
  req: InlineEditApplyRequest,
): Promise<InlineEditApplyResult> {
  return post<InlineEditApplyResult>("/api/agent/inline-edit/apply", req);
}
