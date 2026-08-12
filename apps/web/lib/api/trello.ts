/**
 * Cliente da API do Quadro Trello/Kanban do Projeto (`/api/projects/{slug}/trello`).
 */

import { del, get, post, put } from "@/lib/client";

export type CardStatus = "todo" | "in_progress" | "review" | "done";
export type CardPriority = "high" | "medium" | "low";

export interface TrelloCard {
  id: string;
  title: string;
  description: string;
  status: CardStatus;
  priority: CardPriority;
  created_at?: string;
  updated_at?: string;
  created_by_agent?: boolean;
}

export interface ListTrelloCardsResponse {
  project: string;
  count: number;
  cards: TrelloCard[];
}

export async function getProjectTrelloCards(slug: string): Promise<ListTrelloCardsResponse> {
  return get<ListTrelloCardsResponse>(`/api/projects/${encodeURIComponent(slug)}/trello`);
}

export async function createProjectTrelloCard(
  slug: string,
  data: {
    title: string;
    description?: string;
    status?: CardStatus;
    priority?: CardPriority;
    created_by_agent?: boolean;
  }
): Promise<{ ok: boolean; card: TrelloCard }> {
  return post<{ ok: boolean; card: TrelloCard }>(`/api/projects/${encodeURIComponent(slug)}/trello`, data);
}

export async function updateProjectTrelloCard(
  slug: string,
  cardId: string,
  data: {
    title?: string;
    description?: string;
    status?: CardStatus;
    priority?: CardPriority;
  }
): Promise<{ ok: boolean; card: TrelloCard }> {
  return put<{ ok: boolean; card: TrelloCard }>(
    `/api/projects/${encodeURIComponent(slug)}/trello/${encodeURIComponent(cardId)}`,
    data
  );
}

export async function deleteProjectTrelloCard(
  slug: string,
  cardId: string
): Promise<{ ok: boolean; id: string }> {
  return del<{ ok: boolean; id: string }>(
    `/api/projects/${encodeURIComponent(slug)}/trello/${encodeURIComponent(cardId)}`
  );
}
