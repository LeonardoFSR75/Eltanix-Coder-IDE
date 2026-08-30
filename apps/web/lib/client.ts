/**
 * Cliente usado no browser. Fala apenas com o proxy do Next (`/api/gateway`),
 * que anexa a credencial no servidor — nada de chave no bundle.
 */

const GATEWAY = "/api/gateway";

/** Erro de resposta HTTP não-ok, com o status preservado — quem chama pode
 * distinguir "não encontrado" (ex.: arquivo opcional ainda não criado) de um
 * erro de verdade sem precisar adivinhar pela mensagem.
 *
 * `body` guarda o payload de erro já parseado (quando é JSON) — inclui o
 * shape RFC 7807 (`type`/`title`/`detail`/`status`) quando o backend o
 * emite, para quem precisa reagir ao `type` e não só mostrar o texto. */
export class HttpError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

/** Lê o corpo de erro uma vez, monta a mensagem legível e lança o `HttpError`
 * já com o payload estruturado anexado. */
async function failFrom(response: Response): Promise<never> {
  const { message, body } = await describeError(response);
  throw new HttpError(message, response.status, body);
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) await failFrom(response);
  return (await response.json()) as T;
}

/** Como `get`, mas devolve `null` num `204 No Content` (ou corpo vazio) — para
 * endpoints em que "sem dado" é um desfecho normal, não um erro. Ex.: as
 * gutters de cobertura, que respondem 204 quando o projeto não tem relatório. */
export async function getOrNull<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  const response = await fetch(`${GATEWAY}${path}`, { cache: "no-store", signal });
  if (!response.ok) await failFrom(response);
  if (response.status === 204) return null;
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : null;
}

export async function post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (!response.ok) await failFrom(response);
  return (await response.json()) as T;
}

/** Como `post`, mas devolve `null` quando o backend responde `204 No Content`
 * (ou um corpo vazio). Para endpoints em que "sem resultado" é um desfecho
 * normal e não um erro — ex.: o autocompletar inline, que responde 204 quando
 * não há sugestão a mostrar. */
export async function postOrNull<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T | null> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (!response.ok) await failFrom(response);
  if (response.status === 204) return null;
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : null;
}

export async function put<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) await failFrom(response);
  return (await response.json()) as T;
}

export async function patch<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) await failFrom(response);
  return (await response.json()) as T;
}

export async function del<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${GATEWAY}${path}`, {
    method: "DELETE",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!response.ok) await failFrom(response);
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
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
    signal,
  });

  if (!response.ok) await failFrom(response);
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
export type LoginResult = { mfaRequired: false } | { mfaRequired: true; mfaToken: string };

export async function login(username: string, password: string): Promise<LoginResult> {
  const response = await fetch("/api/session", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) await failFrom(response);
  // 204 = sessão criada; 200 = falta o 2º fator.
  if (response.status === 200) {
    const body = await response.json();
    if (body?.mfaRequired) return { mfaRequired: true, mfaToken: body.mfaToken };
  }
  return { mfaRequired: false };
}

export async function loginMfa(mfaToken: string, code: string): Promise<void> {
  const response = await fetch("/api/session/mfa", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ mfaToken, code }),
  });
  if (!response.ok) await failFrom(response);
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

async function describeError(response: Response): Promise<{ message: string; body: unknown }> {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    // RFC 7807 usa `detail` (string) e `title`; o FastAPI usa `detail`
    // (string | array) e alguns handlers usam `error`. `title` entra como
    // fonte secundária para quando o backend passar a emitir problem+json.
    const detail = body?.detail ?? body?.error ?? body?.title;

    // FastAPI/Pydantic 422: detail é um array de { loc, msg, type }
    if (Array.isArray(detail) && detail.length > 0) {
      const message = detail
        .map((e: { msg?: string; loc?: string[] }) => {
          const field = e.loc?.filter((p) => p !== "body").join(".") ?? "";
          const msg = e.msg?.replace(/^Value error,\s*/i, "") ?? "erro de validação";
          return field ? `${field}: ${msg}` : msg;
        })
        .join(" | ");
      return { message, body };
    }

    if (typeof detail === "string") {
      const normalized = detail.trim();
      if (normalized.startsWith("Sessão desconhecida:")) {
        return {
          message:
            "Sessão reaberta automaticamente após o reinício do serviço. Se o histórico não aparecer, recarregue a aba.",
          body,
        };
      }
      // RFC 7807: se veio `title` além do `detail`, prefixa para dar contexto.
      const title = typeof body?.title === "string" ? body.title.trim() : "";
      const message = title && title !== normalized ? `${title}: ${normalized}` : normalized;
      return { message, body };
    }
    if (detail?.error?.message) return { message: detail.error.message, body };
    return { message: fallback, body };
  } catch {
    return { message: fallback, body: undefined };
  }
}
