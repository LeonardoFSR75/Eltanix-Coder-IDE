import { del, get, post } from "@/lib/client";

export type BrowserAction = "navigate" | "click" | "type" | "screenshot" | "content";
export type BrowserEngine = "auto" | "lightpanda" | "chromium";

export interface BrowserActionResult {
  ok: boolean;
  url?: string;
  title?: string;
  status?: number;
  duration_ms?: number;
  engine_used?: string;
  image_base64?: string;
  text?: string;
  console_errors?: string[];
  page_errors?: string[];
}

export interface BrowserActionParams {
  sessionId: string;
  action: BrowserAction;
  url?: string;
  selector?: string;
  x?: number;
  y?: number;
  text?: string;
  engine?: BrowserEngine;
}

export function browserAction({
  sessionId,
  action,
  url,
  selector,
  x,
  y,
  text,
  engine = "auto",
}: BrowserActionParams): Promise<BrowserActionResult> {
  return post<BrowserActionResult>("/api/browser/action", {
    session_id: sessionId,
    action,
    url,
    selector,
    x,
    y,
    text,
    engine,
  });
}

export function closeBrowserSession(
  sessionId: string,
): Promise<{ closed: boolean; replay?: boolean }> {
  return del<{ closed: boolean; replay?: boolean }>(
    `/api/browser/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export interface ReplayAction {
  t_offset_ms: number;
  action: string;
  summary: string;
}

export interface ReplayDetail {
  session_id: string;
  project: string | null;
  started_at: number;
  duration_ms: number | null;
  actions: ReplayAction[];
  network: NetworkLogEntry[];
  trace_key: string | null;
  video_key: string | null;
  trace_url?: string;
  video_url?: string;
}

/** `404` é o caso normal quando a sessão nunca foi fechada (replay só existe
 * depois de `DELETE /sessions/{id}`) — o chamador trata como "sem replay
 * ainda", não como erro. */
export function getBrowserReplay(sessionId: string): Promise<ReplayDetail> {
  return get<ReplayDetail>(`/api/browser/replays/${encodeURIComponent(sessionId)}`);
}

export interface NetworkLogEntry {
  method: string;
  url: string;
  resource_type?: string | null;
  status: number | null;
  duration_ms: number | null;
  size_bytes: number | null;
  /** Só presente no log persistido do replay (Fase 4c) — offset desde o
   * início da sessão, mesma base de tempo de `ReplayAction.t_offset_ms`. */
  t_offset_ms?: number;
}

export function getBrowserNetworkLog(sessionId: string): Promise<{ requests: NetworkLogEntry[] }> {
  return get<{ requests: NetworkLogEntry[] }>(
    `/api/browser/sessions/${encodeURIComponent(sessionId)}/network`,
  );
}

export interface BrowserStreamTicket {
  ticket: string;
  expires_in: number;
}

export function getBrowserStreamTicket(sessionId: string): Promise<BrowserStreamTicket> {
  return post<BrowserStreamTicket>(
    `/api/browser/sessions/${encodeURIComponent(sessionId)}/stream-ticket`,
    {},
  );
}

/** Monta a URL do WebSocket de streaming ao vivo — mesmo padrão de `lib/lsp.ts`:
 * o ticket viaja na query string porque o browser não manda header customizado
 * ao abrir um WebSocket, e a rota (`ws_router`, sem `AuthDep`) só aceita quem
 * chega com um ticket de uso único válido. */
export function buildBrowserStreamUrl(sessionId: string, ticket: string): string {
  const origem =
    process.env.NEXT_PUBLIC_API_ORIGIN ??
    `${window.location.protocol}//${window.location.hostname}:5401`;
  return (
    `${origem.replace(/^http/, "ws")}/api/browser/sessions/${encodeURIComponent(sessionId)}/stream` +
    `?ticket=${encodeURIComponent(ticket)}`
  );
}
