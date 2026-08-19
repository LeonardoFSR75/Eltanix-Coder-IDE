/**
 * Cliente API para o subsistema de Analytics ML e Auto-Diagnósticos.
 */

import { get, post } from "@/lib/client";

export interface AnalyticsDashboardSummary {
  total_trajectories: number;
  total_failures: number;
  total_clusters: number;
  pending_proposals: number;
  failure_categories: Record<string, number>;
  top_failing_files: Array<{ file: string; failures: number }>;
  recent_trajectories: Array<{
    id: string;
    session_id: string;
    failure_category: string;
    root_cause_hypothesis: string | null;
    status: string;
    created_at: string;
  }>;
}

export interface AutoCorrectionProposal {
  id: string;
  cluster_id: string | null;
  title: string;
  proposal_type: string;
  target_file: string;
  diff_content: string;
  explanation: string;
  confidence_score: number;
  status: string;
  created_at: string | null;
}

/**
 * Obtém o resumo de telemetria e falhas ML.
 */
export async function getAnalyticsDashboard(): Promise<AnalyticsDashboardSummary> {
  return get<AnalyticsDashboardSummary>("/api/analytics/dashboard");
}

/**
 * Lista as propostas de auto-correção pendentes.
 */
export async function listPendingProposals(): Promise<{ proposals: AutoCorrectionProposal[] }> {
  return get<{ proposals: AutoCorrectionProposal[] }>("/api/analytics/proposals");
}

/**
 * Aplica uma proposta de auto-correção.
 */
export async function applyProposal(proposalId: string): Promise<{ status: string; message: string }> {
  return post<{ status: string; message: string }>(`/api/analytics/proposals/${proposalId}/apply`, {});
}
