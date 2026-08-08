"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/AuthContext";
import { useToast } from "@/components/Toast";
import { getHealth, type HealthStatus } from "@/lib/api/health";
import { getMetricsSummary, type Summary } from "@/lib/api/metrics";

import { changePassword } from "@/lib/client";

export default function ProfilePage() {
  const { user, logout } = useAuth();
  const { addToast } = useToast();
  const router = useRouter();

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [metrics, setMetrics] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);

  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  useEffect(() => {
    Promise.all([getHealth(), getMetricsSummary()])
      .then(([h, m]) => {
        setHealth(h);
        setMetrics(m);
      })
      .catch((err) => {
        addToast(err instanceof Error ? err.message : "Falha ao carregar dados do backend.", "error");
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogout = async () => {
    await logout();
    addToast("Sessão encerrada.", "info");
    router.push("/login");
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!oldPassword || !newPassword) {
      addToast("Preencha a senha atual e a nova senha.", "warning");
      return;
    }
    if (newPassword.length < 6) {
      addToast("A nova senha deve ter pelo menos 6 caracteres.", "warning");
      return;
    }
    if (newPassword !== confirmPassword) {
      addToast("A nova senha e a confirmação não conferem.", "warning");
      return;
    }

    setIsChangingPassword(true);
    try {
      await changePassword(oldPassword, newPassword);
      addToast("Senha alterada com sucesso!", "success");
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao alterar senha.", "error");
    } finally {
      setIsChangingPassword(false);
    }
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">👤 Perfil</span>
          <h1>Perfil & Conexão</h1>
          <p>Gestão de sessão, alteração de credenciais e status de conexões da plataforma.</p>
        </div>
        <div className="header-actions">
          <Link href="/settings/git" className="btn-secondary-sm">
            🐙 Conta Git & GitHub
          </Link>
          <button type="button" className="btn-danger-sm" onClick={handleLogout}>
            🚪 Sair
          </button>
        </div>
      </div>

      <div className="grid grid-3-1">
        <div className="panel-box">
          <div className="panel-header">
            <h3>Sessão</h3>
            <span className={`badge-tag ${user ? "green" : "red"}`}>
              {user ? "Conectado" : "Desconectado"}
            </span>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label>Usuário</label>
              <input
                type="text"
                className="input-text font-mono"
                value={user?.username ?? "—"}
                readOnly
              />
            </div>
            <div className="form-group">
              <label>Nome de exibição</label>
              <input
                type="text"
                className="input-text font-mono"
                value={user?.displayName ?? "—"}
                readOnly
              />
            </div>
          </div>
        </div>

        <div className="panel-box">
          <div className="panel-header">
            <h3>Gateway & Roteamento</h3>
          </div>

          {loading && <p className="text-xs text-muted">Carregando…</p>}
          {health && (
            <div className="db-stats-list">
              <div className="db-stat-item">
                <span>Status</span>
                <strong>{health.status}</strong>
              </div>
              <div className="db-stat-item">
                <span>Modelos utilizáveis</span>
                <strong>
                  {health.models_usable} / {health.models_total}
                </strong>
              </div>
              <div className="db-stat-item">
                <span>Perfis de roteamento</span>
                <strong>{health.profiles.join(", ")}</strong>
              </div>
              <div className="db-stat-item">
                <span>Cache exato</span>
                <strong>{health.cache_enabled ? "Ativo" : "Desativado"}</strong>
              </div>
            </div>
          )}
        </div>
      </div>

      <section className="section-block">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🔑 Alterar Senha</h3>
          </div>
          <form onSubmit={handleChangePassword} className="config-form max-w-md">
            <div className="form-group">
              <label htmlFor="old-password-input">Senha Atual</label>
              <input
                id="old-password-input"
                type="password"
                className="input-text"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>
            <div className="form-group">
              <label htmlFor="new-password-input">Nova Senha (mín. 6 caracteres)</label>
              <input
                id="new-password-input"
                type="password"
                className="input-text"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>
            <div className="form-group">
              <label htmlFor="confirm-password-input">Confirmar Nova Senha</label>
              <input
                id="confirm-password-input"
                type="password"
                className="input-text"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>
            <button
              type="submit"
              className="btn-primary"
              disabled={isChangingPassword || !oldPassword || !newPassword || !confirmPassword}
            >
              {isChangingPassword ? "Alterando..." : "Salvar Nova Senha"}
            </button>
          </form>
        </div>
      </section>

      <section className="section-block">
        <div className="panel-box">
          <div className="panel-header">
            <h3>📊 Uso (últimos {metrics?.window_days ?? 30} dias)</h3>
          </div>

          {loading && <p className="text-xs text-muted">Carregando…</p>}
          {metrics && (
            <div className="profile-stats-grid">
              <div className="pstat-box">
                <span className="pstat-num">{metrics.requests}</span>
                <span className="pstat-label">Requests</span>
              </div>
              <div className="pstat-box">
                <span className="pstat-num">{metrics.total_tokens.toLocaleString("pt-BR")}</span>
                <span className="pstat-label">Tokens</span>
              </div>
              <div className="pstat-box">
                <span className="pstat-num">${metrics.cost_usd.toFixed(4)}</span>
                <span className="pstat-label">Custo (USD)</span>
              </div>
              <div className="pstat-box">
                <span className="pstat-num">{(metrics.cache_hit_rate * 100).toFixed(1)}%</span>
                <span className="pstat-label">Cache hit rate</span>
              </div>
            </div>
          )}
          {metrics && metrics.budget.daily_limit_usd > 0 && (
            <p className="text-xs text-muted mt-2">
              Orçamento diário: ${metrics.budget.daily_spent_usd.toFixed(2)} / $
              {metrics.budget.daily_limit_usd.toFixed(2)}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
