import { del, get, post } from "@/lib/client";

export type BrowserAction = "navigate" | "click" | "type" | "screenshot" | "content";

export interface BrowserActionResult {
  ok: boolean;
  url?: string;
  title?: string;
  status?: number;
  duration_ms?: number;
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
}

export function browserAction({
  sessionId,
  action,
  url,
  selector,
  x,
  y,
  text,
}: BrowserActionParams): Promise<BrowserActionResult> {
  return post<BrowserActionResult>("/api/browser/action", {
    session_id: sessionId,
    action,
    url,
    selector,
    x,
    y,
    text,
  });
}

export function closeBrowserSession(sessionId: string): Promise<{ closed: boolean }> {
  return del<{ closed: boolean }>(`/api/browser/sessions/${encodeURIComponent(sessionId)}`);
}

export interface NetworkLogEntry {
  method: string;
  url: string;
  resource_type?: string | null;
  status: number | null;
  duration_ms: number | null;
  size_bytes: number | null;
}

export function getBrowserNetworkLog(sessionId: string): Promise<{ requests: NetworkLogEntry[] }> {
  return get<{ requests: NetworkLogEntry[] }>(
    `/api/browser/sessions/${encodeURIComponent(sessionId)}/network`,
  );
}
