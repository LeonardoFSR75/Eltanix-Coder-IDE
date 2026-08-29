/**
 * Edição inline (Fase 7 do upgrade do agente, estilo Cmd+K) — fala com
 * `POST /api/agent/inline-edit`.
 *
 * Fora do ciclo de sessão do agente de propósito: uma seleção pontual no
 * editor não precisa de sessão/checkpoint completo, só de uma chamada
 * isolada de LLM sobre o trecho selecionado.
 */

import { post } from "@/lib/client";

export interface InlineEditRequest {
  project: string;
  path: string;
  selected_text: string;
  instruction: string;
  context_before?: string;
  context_after?: string;
}

export interface InlineEditResult {
  path: string;
  old_text: string;
  new_text: string;
  before: string;
  after: string;
  diff: string;
  changed_lines: number;
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
