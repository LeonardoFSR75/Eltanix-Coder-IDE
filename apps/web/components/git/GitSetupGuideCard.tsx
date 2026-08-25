"use client";

import React, { useState } from "react";
import { useToast } from "@/components/Toast";

export function GitSetupGuideCard() {
  const { addToast } = useToast();
  const [activeTab, setActiveTab] = useState<"overview" | "git" | "github" | "agent">("overview");

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    addToast(`Copiado para a área de transferência: ${label}`, "success");
  };

  return (
    <div className="panel-box" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <div className="panel-header" style={{ borderBottom: "1px solid var(--border)", paddingBottom: "1rem" }}>
        <div className="flex items-center gap-2">
          <span className="text-xl">📖</span>
          <div>
            <h3 className="m-0 text-base font-semibold">Guia Explicativo: Como Configurar Git & GitHub na Tool</h3>
            <p className="text-xs text-muted m-0">
              Instruções passo a passo para autenticar a IDE, a CLI e o Agente de IA com sua conta Git e GitHub.
            </p>
          </div>
        </div>
      </div>

      {/* Tabs de Navegação */}
      <div
        className="flex gap-2 mt-4 pb-2"
        style={{ borderBottom: "1px solid var(--border)", overflowX: "auto" }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={`btn-secondary-sm ${activeTab === "overview" ? "btn-primary-sm" : ""}`}
          style={{ fontSize: "0.825rem", padding: "0.4rem 0.8rem" }}
        >
          💡 1. Visão Geral
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("git")}
          className={`btn-secondary-sm ${activeTab === "git" ? "btn-primary-sm" : ""}`}
          style={{ fontSize: "0.825rem", padding: "0.4rem 0.8rem" }}
        >
          👤 2. Identidade Git Local
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("github")}
          className={`btn-secondary-sm ${activeTab === "github" ? "btn-primary-sm" : ""}`}
          style={{ fontSize: "0.825rem", padding: "0.4rem 0.8rem" }}
        >
          🔑 3. Token PAT do GitHub
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("agent")}
          className={`btn-secondary-sm ${activeTab === "agent" ? "btn-primary-sm" : ""}`}
          style={{ fontSize: "0.825rem", padding: "0.4rem 0.8rem" }}
        >
          🤖 4. Uso no Agente & IDE
        </button>
      </div>

      {/* Conteúdo da Tab */}
      <div className="mt-4 text-xs" style={{ color: "var(--text)" }}>
        {activeTab === "overview" && (
          <div className="flex flex-col gap-3">
            <div
              className="p-3 rounded-lg"
              style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
            >
              <h4 className="m-0 text-sm font-semibold mb-1" style={{ color: "var(--text)" }}>
                Por que configurar o Git e o GitHub no Eltanix Coder IDE?
              </h4>
              <p className="m-0 text-muted leading-relaxed">
                O Eltanix Coder IDE integra o desenvolvimento local com a inteligência do Agente de IA. Para que o
                Agente consiga efetuar commits em seu nome, sincronizar repositórios, criar Pull Requests e consultar
                Issues, a ferramenta precisa de duas configurações principais:
              </p>
            </div>

            <div className="grid grid-2 gap-3 mt-1">
              <div
                className="p-3 rounded-lg"
                style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
              >
                <div className="font-semibold text-sm mb-1">1. Identidade Git Local (`user.name` & `user.email`)</div>
                <p className="m-0 text-muted leading-relaxed">
                  Garante que todas as alterações gravadas pela IDE ou pelo Agente levem o seu nome e e-mail no histórico
                  do Git.
                </p>
              </div>

              <div
                className="p-3 rounded-lg"
                style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
              >
                <div className="font-semibold text-sm mb-1">2. GitHub Personal Access Token (PAT)</div>
                <p className="m-0 text-muted leading-relaxed">
                  Permite a comunicação segura via API REST com o GitHub para clonagem de repositórios privados, envio de
                  branches, abertura de PRs e inspeção de CI/CD.
                </p>
              </div>
            </div>
          </div>
        )}

        {activeTab === "git" && (
          <div className="flex flex-col gap-3">
            <p className="m-0 text-muted leading-relaxed">
              O Git exige um <strong>Nome de Usuário</strong> e um <strong>E-mail</strong> registrados para assinar os commits.
              Você pode configurar isso diretamente no formulário abaixo ou via terminal.
            </p>

            <div className="p-3 rounded-lg" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
              <div className="font-semibold text-sm mb-2">Opção A: Via Formulário nesta página</div>
              <p className="m-0 text-muted leading-relaxed">
                Utilize o card <strong>"Identidade do Autor Git (user.name / user.email)"</strong> abaixo. Escolha se deseja
                gravar como configuração <strong>Global</strong> (válida para todo o sistema) ou <strong>Local do Projeto</strong>.
              </p>
            </div>

            <div className="p-3 rounded-lg" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
              <div className="flex justify-between items-center mb-2">
                <span className="font-semibold text-sm">Opção B: Via Terminal / CLI</span>
                <button
                  type="button"
                  className="btn-secondary-sm"
                  onClick={() =>
                    copyToClipboard(
                      'git config --global user.name "Seu Nome"\ngit config --global user.email "seu.email@exemplo.com"',
                      "Comandos Git"
                    )
                  }
                >
                  📋 Copiar Comandos
                </button>
              </div>
              <pre
                className="p-2 rounded font-mono text-xs overflow-x-auto m-0"
                style={{ background: "rgba(0,0,0,0.3)", color: "#38bdf8" }}
              >
                git config --global user.name &quot;Seu Nome&quot;{"\n"}
                git config --global user.email &quot;seu.email@exemplo.com&quot;
              </pre>
            </div>
          </div>
        )}

        {activeTab === "github" && (
          <div className="flex flex-col gap-3">
            <p className="m-0 text-muted leading-relaxed">
              Siga os passos abaixo para gerar um Personal Access Token (PAT) no GitHub e conectá-lo à ferramenta:
            </p>

            <ol className="m-0 pl-4 flex flex-col gap-2 text-muted">
              <li>
                <strong>Passo 1:</strong> Acesse o GitHub e vá em{" "}
                <a
                  href="https://github.com/settings/tokens/new?scopes=repo,read:user,user:email,workflow&description=Eltanix Coder IDE+IDE"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 hover:underline font-semibold"
                >
                  GitHub Token Generator ↗
                </a>.
              </li>
              <li>
                <strong>Passo 2:</strong> Certifique-se de selecionar os seguintes escopos de permissão:
                <ul className="pl-4 mt-1 list-disc">
                  <li>
                    <code className="font-mono text-xs px-1 bg-black/30 rounded">repo</code> — Acesso completo a repositórios
                    (necessário para commits, pushes e PRs)
                  </li>
                  <li>
                    <code className="font-mono text-xs px-1 bg-black/30 rounded">read:user</code> e{" "}
                    <code className="font-mono text-xs px-1 bg-black/30 rounded">user:email</code> — Leitura dos dados do perfil
                  </li>
                  <li>
                    <code className="font-mono text-xs px-1 bg-black/30 rounded">workflow</code> — (Opcional) Acompanhar pipelines de
                    CI/CD do GitHub Actions
                  </li>
                </ul>
              </li>
              <li>
                <strong>Passo 3:</strong> Clique em <strong>Generate Token</strong> no final da página do GitHub e copie a chave gerada (inicia com <code className="font-mono">ghp_</code>).
              </li>
              <li>
                <strong>Passo 4:</strong> Cole a chave no campo <strong>"GitHub Personal Access Token (PAT)"</strong> no card acima.
              </li>
              <li>
                <strong>Passo 5:</strong> Clique em <strong>🔍 Testar Conexão</strong> para confirmar a validade e em <strong>💾 Salvar Token no .env</strong>.
              </li>
            </ol>
          </div>
        )}

        {activeTab === "agent" && (
          <div className="flex flex-col gap-3">
            <p className="m-0 text-muted leading-relaxed">
              Após configurar sua identidade e o token do GitHub, o Agente de IA e a IDE do Eltanix Coder IDE ganham superpoderes:
            </p>

            <div className="grid grid-2 gap-3">
              <div className="p-3 rounded-lg" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                <div className="font-semibold text-sm mb-1">🤖 Agente Autónomo de Git</div>
                <p className="m-0 text-muted leading-relaxed">
                  Você pode pedir no chat do Agente: <em>"Crie um commit com as alterações atuais e abra um PR no GitHub"</em>. O agente usará a API do GitHub e a CLI local automaticamente.
                </p>
              </div>

              <div className="p-3 rounded-lg" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                <div className="font-semibold text-sm mb-1">💻 Painel Integrado da IDE</div>
                <p className="m-0 text-muted leading-relaxed">
                  No menu lateral da IDE, a aba <strong>Git</strong> exibirá o diff de arquivos, a lista de branches e permitirá staging/commit com um clique.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
