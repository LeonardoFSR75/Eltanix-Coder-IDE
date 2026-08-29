"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import {
  activateMfa,
  disableMfa,
  getMfaStatus,
  MFA_QR_URL,
  regenerateRecoveryCodes,
  startMfaSetup,
  type MfaSetup,
  type MfaStatus,
} from "@/lib/api/mfa";

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <div className="mfa-recovery">
      <p className="text-xs" style={{ color: "var(--warning, #d18616)" }}>
        Guarde estes códigos de recuperação num lugar seguro. Cada um serve uma vez e é a única
        forma de entrar se você perder o app autenticador. <strong>Não serão mostrados de novo.</strong>
      </p>
      <pre className="mfa-recovery-list font-mono">{codes.join("\n")}</pre>
      <div className="mfa-actions">
        <button
          type="button"
          className="btn-secondary-sm"
          onClick={() => {
            void navigator.clipboard?.writeText(codes.join("\n"));
          }}
        >
          Copiar
        </button>
        <button type="button" className="btn-primary" onClick={onDone}>
          Já guardei
        </button>
      </div>
    </div>
  );
}

export default function MfaSettings() {
  const { addToast } = useToast();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // fluxo de enrollment
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [enrollCode, setEnrollCode] = useState("");

  // códigos recém-gerados (enrollment ou regeneração)
  const [freshCodes, setFreshCodes] = useState<string[] | null>(null);

  // desativar / regenerar
  const [mgmtPassword, setMgmtPassword] = useState("");
  const [mgmtCode, setMgmtCode] = useState("");
  const [mgmtMode, setMgmtMode] = useState<"none" | "disable" | "regen">("none");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await getMfaStatus());
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao carregar status do 2FA.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleStartSetup = async () => {
    setBusy(true);
    try {
      setSetup(await startMfaSetup());
      setEnrollCode("");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao iniciar o 2FA.", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleActivate = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { recovery_codes } = await activateMfa(enrollCode.trim());
      setFreshCodes(recovery_codes);
      setSetup(null);
      setEnrollCode("");
      addToast("2FA ativado.", "success");
      await refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Código inválido.", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleMgmtSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mgmtMode === "disable") {
        await disableMfa(mgmtPassword, mgmtCode.trim());
        addToast("2FA desativado.", "success");
      } else {
        const { recovery_codes } = await regenerateRecoveryCodes(mgmtPassword, mgmtCode.trim());
        setFreshCodes(recovery_codes);
        addToast("Novos códigos de recuperação gerados.", "success");
      }
      setMgmtMode("none");
      setMgmtPassword("");
      setMgmtCode("");
      await refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Senha ou código inválido.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel-box">
      <div className="panel-header">
        <h3>🔐 Verificação em duas etapas (2FA)</h3>
        {status && (
          <span className={`badge-tag ${status.enabled ? "green" : "red"}`}>
            {status.enabled ? "Ativa" : "Inativa"}
          </span>
        )}
      </div>

      {loading && <p className="text-xs text-muted">Carregando…</p>}

      {freshCodes && (
        <RecoveryCodes codes={freshCodes} onDone={() => setFreshCodes(null)} />
      )}

      {!loading && !freshCodes && status && !status.enabled && !setup && (
        <div className="config-form max-w-md">
          <p className="text-xs text-muted">
            Protege o login com um código de uso único de um app autenticador (Google
            Authenticator, Aegis, 1Password…), além da senha.
          </p>
          <button type="button" className="btn-primary" disabled={busy} onClick={handleStartSetup}>
            {busy ? "Gerando…" : "Configurar 2FA"}
          </button>
        </div>
      )}

      {!freshCodes && setup && (
        <form onSubmit={handleActivate} className="config-form max-w-md">
          <p className="text-xs text-muted">
            1. Escaneie o QR no seu app autenticador (ou digite a chave manualmente).
          </p>
          <img
            src={MFA_QR_URL}
            alt="QR code para configurar o 2FA"
            width={185}
            height={185}
            style={{ background: "#fff", padding: 8, borderRadius: 8 }}
          />
          <div className="form-group">
            <label>Chave (entrada manual)</label>
            <input type="text" className="input-text font-mono" value={setup.secret} readOnly />
          </div>
          <div className="form-group">
            <label htmlFor="enroll-code">2. Digite o código gerado para confirmar</label>
            <input
              id="enroll-code"
              type="text"
              inputMode="numeric"
              className="input-text font-mono"
              value={enrollCode}
              onChange={(e) => setEnrollCode(e.target.value)}
              placeholder="000000"
              autoComplete="one-time-code"
            />
          </div>
          <div className="mfa-actions">
            <button type="button" className="btn-secondary-sm" onClick={() => setSetup(null)}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={busy || enrollCode.trim().length < 6}>
              {busy ? "Confirmando…" : "Ativar"}
            </button>
          </div>
        </form>
      )}

      {!loading && !freshCodes && status?.enabled && mgmtMode === "none" && (
        <div className="config-form max-w-md">
          <p className="text-xs text-muted">
            Códigos de recuperação restantes: <strong>{status.recovery_codes_remaining}</strong>
          </p>
          <div className="mfa-actions">
            <button type="button" className="btn-secondary-sm" onClick={() => setMgmtMode("regen")}>
              Gerar novos códigos de recuperação
            </button>
            <button type="button" className="btn-danger-sm" onClick={() => setMgmtMode("disable")}>
              Desativar 2FA
            </button>
          </div>
        </div>
      )}

      {mgmtMode !== "none" && (
        <form onSubmit={handleMgmtSubmit} className="config-form max-w-md">
          <p className="text-xs text-muted">
            {mgmtMode === "disable"
              ? "Confirme com sua senha e um código para desativar o 2FA."
              : "Confirme com sua senha e um código. Os códigos antigos deixam de valer."}
          </p>
          <div className="form-group">
            <label htmlFor="mgmt-pass">Senha atual</label>
            <input
              id="mgmt-pass"
              type="password"
              className="input-text"
              value={mgmtPassword}
              onChange={(e) => setMgmtPassword(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="mgmt-code">Código (autenticador ou recuperação)</label>
            <input
              id="mgmt-code"
              type="text"
              className="input-text font-mono"
              value={mgmtCode}
              onChange={(e) => setMgmtCode(e.target.value)}
              placeholder="000000"
              autoComplete="one-time-code"
            />
          </div>
          <div className="mfa-actions">
            <button
              type="button"
              className="btn-secondary-sm"
              onClick={() => {
                setMgmtMode("none");
                setMgmtPassword("");
                setMgmtCode("");
              }}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className={mgmtMode === "disable" ? "btn-danger-sm" : "btn-primary"}
              disabled={busy || !mgmtPassword || !mgmtCode.trim()}
            >
              {busy
                ? "Processando…"
                : mgmtMode === "disable"
                  ? "Desativar 2FA"
                  : "Gerar códigos"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
