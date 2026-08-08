/**
 * Cliente usado no browser. Fala apenas com o proxy do Next (`/api/gateway`),
 * que anexa a credencial no servidor — nada de chave no bundle.
 */

const GATEWAY = "/api/gateway";

/** Erro de resposta HTTP não-ok, com o status preservado — quem chama pode
 * distinguir "não encontrado" (ex.: arquivo opcional ainda não criado) de um
 * erro de verdade sem precisar adivinhar pela mensagem. */
export class HttpError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

function getAuthHeaders(): Record<string, string> {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("sicoobito_api_key");
    if (token) return { Authorization: `Bearer ${token}` };
  }
  return {};
}

export async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    cache: "no-store",
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new HttpError(await describeError(response), response.status);
  return (await response.json()) as T;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw new HttpError(await describeError(response), response.status);
  return (await response.json()) as T;
}

export async function put<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "PUT",
    headers: { "content-type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new HttpError(await describeError(response), response.status);
  return (await response.json()) as T;
}

export async function patch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "PATCH",
    headers: { "content-type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new HttpError(await describeError(response), response.status);
  return (await response.json()) as T;
}

export async function del<T>(path: string): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "DELETE",
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new HttpError(await describeError(response), response.status);
  return (await response.json()) as T;
}

/**
 * Consome um endpoint SSE, entregando cada evento já parseado.
 *
 * O `EventSource` do browser só faz GET e não permite corpo, mas o agente
 * precisa receber as decisões de aprovação num POST — daí a leitura manual do
 * stream.
 */
export async function streamEvents(
  path: string,
  body: unknown,
  onEvent: (event: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body ?? {}),
    signal,
  });

  if (!response.ok) throw new HttpError(await describeError(response), response.status);
  if (!response.body) throw new Error("Resposta sem corpo.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    // Eventos SSE são separados por linha em branco; um chunk da rede pode
    // conter vários ou partir um no meio.
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        onEvent(JSON.parse(payload));
      } catch {
        // Um evento malformado não deve derrubar o stream inteiro.
      }
    }
  }
}

/**
 * Login/logout de sessão — fala com `/api/session` (não com o gateway
 * genérico), que é o único Route Handler capaz de setar o cookie httpOnly de
 * resposta. Ver `app/api/session/route.ts`.
 */
export async function login(username: string, password: string): Promise<void> {
  const response = await fetch("/api/session", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new HttpError(await describeError(response), response.status);
}

export async function logout(): Promise<void> {
  await fetch("/api/session", { method: "DELETE" });
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await post<{ status: string }>("/api/auth/change-password", {
    old_password: oldPassword,
    new_password: newPassword,
  });
}

async function describeError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail ?? body?.error;
    if (typeof detail === "string") return detail;
    if (detail?.error?.message) return detail.error.message;
    return `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}
