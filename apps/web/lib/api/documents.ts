/**
 * Cliente real de documentos (RAG) — fala com `/api/documents` no backend.
 *
 * O upload não passa por `del`/`post` de `lib/client.ts`: o PUT do arquivo vai
 * direto para o MinIO via URL pré-assinada, fora do proxy do Next (que lê o
 * corpo como texto e corromperia um PDF binário).
 */

import { del, get, post } from "@/lib/client";

export interface DocumentSummary {
  id: string;
  project_slug: string | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  page_count: number | null;
  chunk_count: number;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  uploaded_at: string;
  indexed_at: string | null;
}

export interface DocumentSearchHit {
  document_id: string;
  filename: string;
  chunk_index: number;
  page_number: number | null;
  content: string;
  token_count: number;
  score: number;
  vector_rank: number | null;
  text_rank: number | null;
}

export async function listDocuments(project?: string | null): Promise<DocumentSummary[]> {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  const { documents } = await get<{ documents: DocumentSummary[] }>(`/api/documents${query}`);
  return documents;
}

export async function getDocument(documentId: string): Promise<DocumentSummary> {
  return get<DocumentSummary>(`/api/documents/${documentId}`);
}

export async function requestUploadUrl(
  file: File,
  project?: string | null,
): Promise<{ document_id: string; upload_url: string }> {
  return post<{ document_id: string; upload_url: string }>("/api/documents/upload-url", {
    filename: file.name,
    content_type: file.type || "application/pdf",
    size_bytes: file.size,
    project: project || undefined,
  });
}

export async function uploadToPresignedUrl(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "content-type": file.type || "application/pdf" },
    body: file,
  });
  if (!response.ok) {
    throw new Error(`Falha ao enviar arquivo para o armazenamento (${response.status}).`);
  }
}

export async function confirmUpload(documentId: string): Promise<{ status: string }> {
  return post<{ status: string }>(`/api/documents/${documentId}/confirm`);
}

export async function uploadDocument(file: File, project?: string | null): Promise<string> {
  const { document_id, upload_url } = await requestUploadUrl(file, project);
  await uploadToPresignedUrl(upload_url, file);
  await confirmUpload(document_id);
  return document_id;
}

export async function deleteDocument(documentId: string): Promise<void> {
  await del(`/api/documents/${documentId}`);
}

export async function searchDocuments(
  query: string,
  limit = 8,
  project?: string | null,
): Promise<DocumentSearchHit[]> {
  const { hits } = await post<{ hits: DocumentSearchHit[] }>("/api/documents/search", {
    query,
    limit,
    project: project || undefined,
  });
  return hits;
}
