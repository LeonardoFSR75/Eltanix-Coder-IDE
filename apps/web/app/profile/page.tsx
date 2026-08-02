"use client";

import React, { useState, useEffect } from "react";
import { useAuth } from "@/components/providers/AuthContext";
import { useToast } from "@/components/Toast";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LocalDB } from "@/lib/db";

interface ApiKey {
  id: string;
  name: string;
  token: string;
  created: string;
}

export default function ProfilePage() {
  const { user, updateUser, logout } = useAuth();
  const { addToast } = useToast();
  const router = useRouter();

  // ✅ FIX: Estado local inicializado a partir do usuário autenticado atual
  const [name, setName] = useState(user?.name || "Leonardo Silva");
  const [email, setEmail] = useState(user?.email || "leonardo@sicoobito.local");
  const [role, setRole] = useState<"Admin" | "Engenheiro de IA" | "Auditor" | "Desenvolvedor">(
    user?.role || "Engenheiro de IA"
  );
  const [avatar, setAvatar] = useState(user?.avatar || "⚡");
  const [bio, setBio] = useState(
    "Engenheiro de Inteligência Artificial focado no desenvolvimento de agentes autônomos locais, busca vetorial no ChromaDB e integração MCP."
  );

  // ✅ FIX: Sincronizar estado quando o usuário carrega (pode ser null no início)
  useEffect(() => {
    if (user) {
      setName(user.name);
      setEmail(user.email);
      setRole(user.role);
      setAvatar(user.avatar);
    }
  }, [user]);

  const [userApiKeys, setUserApiKeys] = useState<ApiKey[]>([
    { id: "key-1", name: "IDE Agent Secret Key", token: "scbt_live_9941a8e22b...", created: "2026-07-20" },
    { id: "key-2", name: "ChromaDB Read-Write Key", token: "scbt_live_8831b7f11c...", created: "2026-07-28" },
  ]);
  const [newKeyName, setNewKeyName] = useState("");

  // ✅ FIX: Usa updateUser (mantém ID e token do usuário) ao invés de login (cria novo ID)
  const handleUpdateProfile = (e: React.FormEvent) => {
    e.preventDefault();
    updateUser({ name, email, role, avatar });

    LocalDB.addAuditLog({
      actor: name || "Usuário",
      module: "Auth",
      action: "Atualização de Dados do Perfil",
      details: `Perfil alterado para ${name} (${role}) com e-mail ${email}.`,
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast("Perfil atualizado e salvo com sucesso no banco de dados!", "success");
  };

  const handleLogout = () => {
    LocalDB.addAuditLog({
      actor: user?.name || "Usuário",
      module: "Auth",
      action: "Encerramento de Sessão (Logout)",
      details: "Sessão encerrada voluntariamente.",
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    logout();
    addToast("Você saiu da sua conta.", "info");
    router.push("/login");
  };

  const handleGenerateApiKey = () => {
    if (!newKeyName.trim()) return;
    const newKey: ApiKey = {
      id: `key-${Date.now()}`,
      name: newKeyName,
      token: `scbt_live_${Math.random().toString(36).substring(2, 12)}...`,
      created: new Date().toISOString().split("T")[0] ?? "",
    };
    setUserApiKeys((prev) => [...prev, newKey]);

    LocalDB.addAuditLog({
      actor: user?.name || "Usuário",
      module: "Auth",
      action: "Geração de Chave API",
      details: `Nova chave de API "${newKeyName}" gerada com permissões ativas.`,
      riskLevel: "medium",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    setNewKeyName("");
    addToast(`Nova chave API "${newKeyName}" gerada com sucesso!`, "success");
  };

  const handleDeleteApiKey = (id: string) => {
    const keyRevoked = userApiKeys.find((k) => k.id === id);
    setUserApiKeys((prev) => prev.filter((k) => k.id !== id));

    LocalDB.addAuditLog({
      actor: user?.name || "Usuário",
      module: "Auth",
      action: "Revogação de Chave API",
      details: `Chave de API "${keyRevoked?.name || id}" revogada e desativada.`,
      riskLevel: "medium",
      ipAddress: "127.0.0.1",
      status: "warning",
    });

    addToast("Chave API revogada.", "info");
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">👤 Gestão de Identidade & Perfil</span>
          <h1>Perfil do Usuário & Credenciais</h1>
          <p>Gerencie suas informações pessoais, chaves de API, biometrias e preferências de sistema.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn-danger-sm" onClick={handleLogout}>
            🚪 Sair da Conta (Logout)
          </button>
          <Link href="/login" className="btn-secondary">
            🔄 Alternar Conta
          </Link>
        </div>
      </div>

      <div className="grid grid-3-1">
        {/* Painel de Edição de Perfil */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Informações do Perfil</h3>
            <span className="badge-tag green">Autenticado</span>
          </div>

          <form onSubmit={handleUpdateProfile} className="config-form">
            <div className="avatar-selector-grid">
              <label className="pane-label">Selecione seu Ícone de Avatar:</label>
              <div className="avatar-options">
                {["⚡", "🛡️", "🔍", "💻", "🧠", "🚀", "🤖", "🌐"].map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    className={`avatar-option-btn ${avatar === emoji ? "active" : ""}`}
                    onClick={() => setAvatar(emoji)}
                    aria-label={`Selecionar avatar ${emoji}`}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-2">
              <div className="form-group">
                <label htmlFor="user-name">Nome Completo</label>
                <input
                  id="user-name"
                  type="text"
                  className="input-text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="user-email">E-mail Corporativo</label>
                <input
                  id="user-email"
                  type="email"
                  className="input-text"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="grid grid-2">
              <div className="form-group">
                <label htmlFor="user-role-select">Função / Perfil no Sistema</label>
                <select
                  id="user-role-select"
                  value={role}
                  onChange={(e) => setRole(e.target.value as "Admin" | "Engenheiro de IA" | "Auditor" | "Desenvolvedor")}
                  className="input-select"
                >
                  <option value="Engenheiro de IA">⚡ Engenheiro de IA</option>
                  <option value="Admin">🛡️ Administrador do Sistema</option>
                  <option value="Auditor">🔍 Auditor de Segurança</option>
                  <option value="Desenvolvedor">💻 Desenvolvedor Fullstack</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="user-method">Método de Autenticação Atual</label>
                <input
                  id="user-method"
                  type="text"
                  className="input-text font-mono"
                  value={user?.authMethod === "passkey" ? "Hardware Passkey (FIDO2)" : "E-mail e Senha"}
                  readOnly
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="user-bio">Biografia / Descrição Técnica</label>
              <textarea
                id="user-bio"
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                className="input-textarea"
                rows={3}
              />
            </div>

            <button type="submit" className="btn-primary glow-button btn-lg">
              💾 Salvar Alterações de Perfil
            </button>
          </form>
        </div>

        {/* Card Resumo do Usuário */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Cartão do Desenvolvedor</h3>
          </div>

          <div className="profile-summary-card">
            <div className="profile-avatar-large">{avatar}</div>
            <h2>{name}</h2>
            <span className="profile-role-tag">{role}</span>
            <p className="profile-email-text">{email}</p>

            <div className="profile-stats-grid">
              <div className="pstat-box">
                <span className="pstat-num">142</span>
                <span className="pstat-label">Queries RAG</span>
              </div>
              <div className="pstat-box">
                <span className="pstat-num">38</span>
                <span className="pstat-label">Notas Grafo</span>
              </div>
              <div className="pstat-box">
                <span className="pstat-num">12</span>
                <span className="pstat-label">Skills Usadas</span>
              </div>
            </div>

            <div className="security-status-box mb-4">
              <span className="pulse-dot-green" /> Biometria FIDO2 Ativa
            </div>

            <button
              type="button"
              className="btn-danger-sm btn-block"
              onClick={handleLogout}
            >
              🚪 Sair da Conta (Logout)
            </button>
          </div>
        </div>
      </div>

      {/* Gestão de Chaves API do Usuário */}
      <section className="section-block">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🔑 Chaves API & Tokens de Acesso do Usuário</h3>
            <span className="badge-tag blue">{userApiKeys.length} Chaves Ativas</span>
          </div>

          <div className="grid grid-3-1 mb-4">
            <input
              type="text"
              placeholder="Nome/Identificador da nova chave (ex: Agente Secundário)..."
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="input-text"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleGenerateApiKey();
                }
              }}
            />
            <button type="button" className="btn-primary glow-button" onClick={handleGenerateApiKey}>
              + Gerar Nova Chave API
            </button>
          </div>

          <div className="table-responsive">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>Nome da Chave</th>
                  <th>Token de Acesso (Bearer)</th>
                  <th>Data de Criação</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {userApiKeys.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <strong>{key.name}</strong>
                    </td>
                    <td className="font-mono text-xs">{key.token}</td>
                    <td className="text-muted text-xs">{key.created}</td>
                    <td>
                      <button
                        type="button"
                        className="btn-danger-sm"
                        onClick={() => handleDeleteApiKey(key.id)}
                      >
                        🗑️ Revogar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}
