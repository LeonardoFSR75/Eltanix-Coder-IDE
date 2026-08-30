/**
 * "Gutter intelligence" do editor (Onda 1.5) — cobertura de teste e CVEs de
 * dependência por linha, para as decorações de margem do Monaco.
 *
 * Casca fina sobre `lib/client.ts`; a lógica de parsing vive no backend
 * (`/api/quality/*`).
 */

import { get, getOrNull } from "@/lib/client";

export interface FileCoverage {
  covered: number[];
  uncovered: number[];
  partial: number[];
  line_rate: number;
}

export interface CoverageResult {
  path: string;
  format: "cobertura" | "lcov" | "istanbul";
  source: string;
  generated_at: number | null;
  project_line_rate: number;
  file: FileCoverage;
}

/** `null` quando o projeto não tem relatório de cobertura, ou quando o
 * relatório não menciona este arquivo. */
export function getCoverage(
  project: string,
  path: string,
  signal?: AbortSignal,
): Promise<CoverageResult | null> {
  return getOrNull<CoverageResult>(
    `/api/quality/coverage?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
    signal,
  );
}

export type CveSeverity = "critical" | "high" | "moderate" | "medium" | "low" | "unknown";

export interface DependencyMarker {
  line: number;
  package: string;
  severity: CveSeverity;
  ids: string[];
  fix: string | null;
  summary: string;
}

export interface DependencyMarkersResult {
  path?: string;
  ecosystem?: string;
  tool?: string | null;
  tool_available?: boolean;
  supported: boolean;
  scanned_at?: number;
  markers: DependencyMarker[];
}

export function getDependencyMarkers(
  project: string,
  path: string,
  signal?: AbortSignal,
): Promise<DependencyMarkersResult> {
  return get<DependencyMarkersResult>(
    `/api/quality/dependency-markers?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
    signal,
  );
}
