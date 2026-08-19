/**
 * Regras de contexto por glob (Fase 4 do upgrade do agente, estilo
 * `.cursor/rules`) — fala com `/api/agent/context-rules`.
 *
 * Mesmo padrão de `lib/api/approvalPolicy.ts`: o PUT substitui a lista de
 * regras inteira (não há add/remove por índice no backend), a tela edita em
 * estado local e salva de uma vez.
 */

import { get, put } from "@/lib/client";

export interface ContextRule {
  glob: string;
  instructions: string;
}

export interface ContextRulesConfig {
  version: number;
  rules: ContextRule[];
}

export function getContextRules(project: string): Promise<ContextRulesConfig> {
  return get<ContextRulesConfig>(
    `/api/agent/context-rules?project=${encodeURIComponent(project)}`,
  );
}

export function updateContextRules(
  project: string,
  rules: ContextRule[],
): Promise<ContextRulesConfig> {
  return put<ContextRulesConfig>("/api/agent/context-rules", { project, rules });
}

export function newContextRule(): ContextRule {
  return { glob: "", instructions: "" };
}
