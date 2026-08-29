/**
 * Gestão do segundo fator (TOTP) do usuário logado — fala com
 * `/api/auth/mfa/*` do backend via o gateway (`lib/client.ts`). A etapa de
 * login em si (desafio + código) fica em `lib/client.ts::loginMfa`, não aqui.
 */

import { get, post } from "@/lib/client";

export interface MfaStatus {
  enabled: boolean;
  pending: boolean;
  recovery_codes_remaining: number;
}

export interface MfaSetup {
  secret: string;
  otpauth_uri: string;
}

export function getMfaStatus(): Promise<MfaStatus> {
  return get<MfaStatus>("/api/auth/mfa/status");
}

export function startMfaSetup(): Promise<MfaSetup> {
  return post<MfaSetup>("/api/auth/mfa/setup");
}

/** URL do QR do segredo pendente — usar direto num `<img src>`. */
export const MFA_QR_URL = "/api/gateway/api/auth/mfa/qr.svg";

export function activateMfa(code: string): Promise<{ status: string; recovery_codes: string[] }> {
  return post("/api/auth/mfa/activate", { code });
}

export function disableMfa(password: string, code: string): Promise<{ status: string }> {
  return post("/api/auth/mfa/disable", { password, code });
}

export function regenerateRecoveryCodes(
  password: string,
  code: string,
): Promise<{ status: string; recovery_codes: string[] }> {
  return post("/api/auth/mfa/recovery-codes", { password, code });
}
