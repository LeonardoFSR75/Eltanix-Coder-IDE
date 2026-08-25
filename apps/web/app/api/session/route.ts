/**
 * Login/logout de sessão — o único lugar que fala com `/api/auth/login` e
 * `/api/auth/logout` do backend, porque só um Route Handler pode setar
 * `Set-Cookie` na resposta ao browser (o proxy genérico de
 * `app/api/gateway/[...path]/route.ts` só repassa cabeçalhos, não monta
 * cookie de resposta).
 */

const BASE_URL = process.env.NOVAAI_STUDIO_API_URL ?? "http://localhost:8000";
const COOKIE_NAME = "novaai_studio_session";

function cookieAttrs(expires?: string): string {
  const parts = ["Path=/", "HttpOnly", "SameSite=Lax"];
  if (process.env.NODE_ENV === "production") parts.push("Secure");
  parts.push(expires ? `Expires=${new Date(expires).toUTCString()}` : "Max-Age=0");
  return parts.join("; ");
}

export async function POST(request: Request): Promise<Response> {
  const { username, password } = await request.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json({ error: `Backend inacessível em ${BASE_URL}: ${message}` }, { status: 502 });
  }

  if (!upstream.ok) {
    const body = await upstream.json().catch(() => ({}));
    return Response.json(
      { error: body?.detail ?? "Usuário ou senha inválidos." },
      { status: upstream.status },
    );
  }

  const { token, expires_at: expiresAt } = await upstream.json();
  return new Response(null, {
    status: 204,
    headers: { "Set-Cookie": `${COOKIE_NAME}=${token}; ${cookieAttrs(expiresAt)}` },
  });
}

export async function DELETE(request: Request): Promise<Response> {
  const cookie = request.headers.get("cookie");
  try {
    await fetch(`${BASE_URL}/api/auth/logout`, {
      method: "POST",
      headers: cookie ? { cookie } : {},
    });
  } catch {
    // Falha ao revogar no backend não pode impedir o browser de esquecer o
    // cookie local — pior caso, a sessão expira sozinha no TTL.
  }
  return new Response(null, {
    status: 204,
    headers: { "Set-Cookie": `${COOKIE_NAME}=; ${cookieAttrs()}` },
  });
}

export const dynamic = "force-dynamic";
