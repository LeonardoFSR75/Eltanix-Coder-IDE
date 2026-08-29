/**
 * Segunda etapa do login com 2º fator. Recebe `{ mfaToken, code }` do browser,
 * troca por uma sessão em `POST /api/auth/login/mfa` do backend e — só aqui —
 * seta o cookie httpOnly. Mesmo motivo de `../route.ts` existir separado do
 * proxy genérico: só um Route Handler monta `Set-Cookie` na resposta.
 */

const BASE_URL = process.env.ELTANIX_API_URL ?? "http://localhost:8000";
const COOKIE_NAME = "eltanix_session";

function cookieAttrs(expires?: string): string {
  const parts = ["Path=/", "HttpOnly", "SameSite=Lax"];
  if (process.env.NODE_ENV === "production") parts.push("Secure");
  parts.push(expires ? `Expires=${new Date(expires).toUTCString()}` : "Max-Age=0");
  return parts.join("; ");
}

export async function POST(request: Request): Promise<Response> {
  const { mfaToken, code } = await request.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${BASE_URL}/api/auth/login/mfa`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mfa_token: mfaToken, code }),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json({ error: `Backend inacessível em ${BASE_URL}: ${message}` }, { status: 502 });
  }

  if (!upstream.ok) {
    const body = await upstream.json().catch(() => ({}));
    return Response.json(
      { error: body?.detail ?? "Código inválido." },
      { status: upstream.status },
    );
  }

  const { token, expires_at: expiresAt } = await upstream.json();
  return new Response(null, {
    status: 204,
    headers: { "Set-Cookie": `${COOKIE_NAME}=${token}; ${cookieAttrs(expiresAt)}` },
  });
}

export const dynamic = "force-dynamic";
