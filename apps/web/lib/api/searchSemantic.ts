/**
 * Busca semântica de código (Onda 1.4) — expõe o `hybrid_search` (RRF: vetor +
 * texto) que já existe no backend em `POST /api/context/search`. Casca fina
 * sobre `lib/client.ts`.
 *
 * Depende de o projeto estar indexado (`POST /api/context/index`); quando não
 * está, `contextIndexStatus` devolve `chunks: 0` e o painel oferece indexar.
 */

import { get, post } from "@/lib/client";

export interface SemanticHit {
  path: string;
  citation: string;
  symbol: string | null;
  parent: string | null;
  kind: string | null;
  start_line: number;
  end_line: number;
  language: string | null;
  token_count: number;
  score: number;
  vector_rank: number | null;
  text_rank: number | null;
  content: string | null;
}

export interface SemanticSearchResult {
  query: string;
  hits: SemanticHit[];
}

export async function semanticSearch(
  project: string,
  query: string,
  opts: { limit?: number; pathPrefix?: string } = {},
  signal?: AbortSignal,
): Promise<SemanticSearchResult> {
  return post<SemanticSearchResult>(
    "/api/context/search",
    {
      project,
      query,
      limit: opts.limit ?? 20,
      path_prefix: opts.pathPrefix,
      include_content: true,
    },
    signal,
  );
}

export interface ContextIndexStatus {
  workspace: string;
  files: number;
  chunks: number;
  total_tokens: number;
  chunks_with_embedding: number;
  files_line_chunked: number;
  by_language: { language: string; files: number }[];
}

export async function contextIndexStatus(project: string): Promise<ContextIndexStatus> {
  return get<ContextIndexStatus>(`/api/context/status?project=${encodeURIComponent(project)}`);
}

export interface ContextIndexReport {
  workspace: string;
  scanned: number;
  indexed: number;
  skipped_unchanged: number;
  removed: number;
  chunks: number;
  embedded: number;
  embedding_failures: number;
  duration_ms: number;
  errors: string[];
}

export async function indexContext(
  project: string,
  force = false,
): Promise<ContextIndexReport> {
  return post<ContextIndexReport>("/api/context/index", { project, force });
}
