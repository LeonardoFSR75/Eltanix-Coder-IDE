<script lang="ts">
  import { login, getAuthUser, logout } from "../client";

  let { isOpen = false, dismissible = true, onSaved } = $props<{
    isOpen?: boolean;
    dismissible?: boolean;
    onSaved?: () => void;
  }>();

  let username = $state("");
  let password = $state("");
  let isValidating = $state(false);
  let error = $state<string | null>(null);

  let currentUser = $derived(getAuthUser());

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;

    isValidating = true;
    error = null;

    const ok = await login(username.trim(), password);
    isValidating = false;

    if (ok) {
      username = "";
      password = "";
      onSaved?.();
    } else {
      error = "Usuário ou senha inválidos.";
    }
  }

  function handleLogout() {
    logout();
  }
</script>

{#if isOpen}
  <div
    class="modal-backdrop"
    role="dialog"
    tabindex="-1"
    onclick={() => dismissible && onSaved?.()}
  >
    <div class="modal-card" role="document" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <div class="login-logo-ring">
          <span class="login-logo-text">S</span>
        </div>
        <h3>Acesso ao Eltanix Coder IDE</h3>
        <p class="hint">Plataforma local-first — login obrigatório por usuário e senha.</p>
        {#if dismissible}
          <button class="btn-close" onclick={() => onSaved?.()} aria-label="Fechar">×</button>
        {/if}
      </div>

      {#if currentUser}
        <div class="user-logged-banner">
          <span>Conectado como <strong>{currentUser.display_name || currentUser.username}</strong></span>
          <button class="btn-logout" onclick={handleLogout}>Sair</button>
        </div>
      {/if}

      <form onsubmit={handleSubmit} class="modal-form">
        <label>
          <span>Usuário</span>
          <input
            type="text"
            bind:value={username}
            placeholder="Digite seu usuário (ex: admin)"
            autocomplete="username"
            required
          />
        </label>

        <label>
          <span>Senha</span>
          <input
            type="password"
            bind:value={password}
            placeholder="Digite sua senha..."
            autocomplete="current-password"
            required
          />
        </label>

        {#if error}
          <p class="error-msg">{error}</p>
        {/if}

        <div class="modal-footer">
          <button
            type="submit"
            class="btn-submit"
            disabled={isValidating || !username.trim() || !password}
          >
            {isValidating ? "Entrando..." : "Entrar"}
          </button>
        </div>
      </form>

      <div class="login-security-tag">
        <span class="dot-green"></span> Autenticação local de sessão — credenciais administradas pela plataforma.
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background: rgba(15, 23, 42, 0.85);
    backdrop-filter: blur(8px);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 9999;
  }
  .modal-card {
    background: #1e293b;
    border: 1px solid rgba(56, 189, 248, 0.2);
    border-radius: 16px;
    width: 420px;
    padding: 24px;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    color: #f8fafc;
    position: relative;
  }
  .modal-header {
    text-align: center;
    margin-bottom: 20px;
    position: relative;
  }
  .login-logo-ring {
    width: 52px;
    height: 52px;
    margin: 0 auto 10px;
    border-radius: 14px;
    background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.4);
  }
  .login-logo-text {
    font-size: 24px;
    font-weight: 900;
    color: #ffffff;
  }
  .modal-header h3 {
    font-size: 1.15rem;
    font-weight: 700;
    color: #f8fafc;
    margin: 0 0 4px 0;
  }
  .btn-close {
    position: absolute;
    top: -8px;
    right: -4px;
    background: transparent;
    border: none;
    color: #94a3b8;
    font-size: 1.4rem;
    cursor: pointer;
  }
  .btn-close:hover {
    color: #ffffff;
  }
  .hint {
    font-size: 0.78rem;
    color: #94a3b8;
    margin: 0;
  }
  .user-logged-banner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(56, 189, 248, 0.1);
    border: 1px solid rgba(56, 189, 248, 0.3);
    padding: 8px 12px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 0.8rem;
    color: #38bdf8;
  }
  .btn-logout {
    background: transparent;
    border: 1px solid rgba(239, 68, 68, 0.4);
    color: #f87171;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .btn-logout:hover {
    background: rgba(239, 68, 68, 0.2);
  }
  .modal-form {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 0.8rem;
    color: #cbd5e1;
    font-weight: 500;
  }
  input[type="text"],
  input[type="password"] {
    background: #0f172a;
    border: 1px solid #334155;
    color: #f8fafc;
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 0.88rem;
    transition: border-color 0.2s;
  }
  input[type="text"]:focus,
  input[type="password"]:focus {
    outline: none;
    border-color: #38bdf8;
    box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
  }
  .error-msg {
    color: #f87171;
    font-size: 0.78rem;
    margin: 0;
  }
  .modal-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
  .btn-submit {
    width: 100%;
    background: linear-gradient(135deg, #0284c7 0%, #4f46e5 100%);
    color: white;
    border: none;
    padding: 10px 16px;
    border-radius: 8px;
    font-weight: 600;
    cursor: pointer;
    font-size: 0.9rem;
    box-shadow: 0 4px 12px rgba(2, 132, 199, 0.3);
    transition: opacity 0.2s, transform 0.1s;
  }
  .btn-submit:hover:not(:disabled) {
    opacity: 0.95;
    transform: translateY(-1px);
  }
  .btn-submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .login-security-tag {
    margin-top: 18px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    font-size: 0.72rem;
    color: #64748b;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .dot-green {
    width: 6px;
    height: 6px;
    background: #10b981;
    border-radius: 50%;
    display: inline-block;
  }
</style>
