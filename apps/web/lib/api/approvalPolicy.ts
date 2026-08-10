/**
 * Política de auto-aprovação por projeto — fala com `/api/agent/approval-policy`.
 *
 * O PUT substitui a lista de regras inteira (não há add/remove por índice no
 * backend): a tela edita a lista em estado local e salva de uma vez, mesmo
 * padrão já usado pelas Instruções no CustomizationsPopover.
 */

import { get, put } from "@/lib/client";

export type EditPathRule = {
  kind: "edit_path_glob";
  tools: ("edit_file" | "write_file")[];
  path_glob: string;
  max_changed_lines: number;
};

export type ExecCommandRule = {
  kind: "exec_command_prefix";
  allowed_prefixes: string[];
};

export type ApprovalRule = EditPathRule | ExecCommandRule;

export interface ApprovalPolicy {
  version: number;
  second_opinion: boolean;
  rules: ApprovalRule[];
}

export function getApprovalPolicy(project: string): Promise<ApprovalPolicy> {
  return get<ApprovalPolicy>(`/api/agent/approval-policy?project=${encodeURIComponent(project)}`);
}

export function updateApprovalPolicy(
  project: string,
  policy: Omit<ApprovalPolicy, "version">,
): Promise<ApprovalPolicy> {
  return put<ApprovalPolicy>("/api/agent/approval-policy", { project, ...policy });
}

export function newEditPathRule(): EditPathRule {
  return { kind: "edit_path_glob", tools: ["edit_file"], path_glob: "", max_changed_lines: 20 };
}

export function newExecCommandRule(): ExecCommandRule {
  return { kind: "exec_command_prefix", allowed_prefixes: [] };
}
