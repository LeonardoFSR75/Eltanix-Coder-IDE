/**
 * Cliente real de notas (Segundo Cérebro) — fala com `/api/notes` no backend.
 *
 * `links` não é enviado pelo cliente: o servidor resolve `[[wikilinks]]` do
 * conteúdo contra os títulos existentes a cada save — é a fonte de verdade
 * única, a mesma que a ferramenta `save_note` do agente usa.
 */

import { del, get, post, put } from "@/lib/client";

export interface NoteRecord {
  id: string;
  title: string;
  content: string;
  tags: string[];
  links: string[];
  created_at: string;
  updated_at: string;
}

export interface NoteSearchHit {
  note_id: string;
  title: string;
  chunk_index: number;
  content: string;
  token_count: number;
  score: number;
  vector_rank: number | null;
  text_rank: number | null;
}

export async function listNotes(): Promise<NoteRecord[]> {
  const { notes } = await get<{ notes: NoteRecord[] }>("/api/notes");
  return notes;
}

export async function createNote(input: {
  title: string;
  content: string;
  tags: string[];
}): Promise<NoteRecord> {
  return post<NoteRecord>("/api/notes", input);
}

export async function updateNote(
  noteId: string,
  input: { title: string; content: string; tags: string[] },
): Promise<NoteRecord> {
  return put<NoteRecord>(`/api/notes/${noteId}`, input);
}

export async function deleteNote(noteId: string): Promise<void> {
  await del(`/api/notes/${noteId}`);
}

export async function searchNotes(query: string, limit = 8): Promise<NoteSearchHit[]> {
  const { hits } = await post<{ hits: NoteSearchHit[] }>("/api/notes/search", { query, limit });
  return hits;
}
