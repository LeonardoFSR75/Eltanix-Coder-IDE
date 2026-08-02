"use client";

/**
 * Painel de terminal, ligado ao sandbox da sessão do agente.
 *
 * Não é um PTY: o backend recebe um comando completo e devolve a saída inteira.
 * O xterm entra como *renderizador* — ele resolve quebra de linha, cores ANSI e
 * seleção de texto, que reimplementados em HTML dariam um resultado pior.
 *
 * A conexão usa um ticket de uso único obtido pelo proxy autenticado: o browser
 * não consegue enviar header ao abrir um WebSocket, e mandar a chave da API na
 * query string a exporia em log e histórico.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { post } from "@/lib/client";

const PROMPT = "\x1b[32m$\x1b[0m ";

export function TerminalPanel({
  sessionId,
  project,
  onSessionCreated,
}: {
  sessionId: string | null;
  project?: string | null;
  onSessionCreated?: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<import("@xterm/xterm").Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const bufferRef = useRef("");
  const [estado, setEstado] = useState<"parado" | "conectando" | "pronto" | "erro">("parado");
  const [detalhe, setDetalhe] = useState<string | null>(null);

  const conectar = useCallback(async () => {
    if (socketRef.current) return;
    setEstado("conectando");
    setDetalhe(null);

    let targetSessionId = sessionId;
    if (!targetSessionId) {
      if (!project) {
        setEstado("parado");
        setDetalhe("Selecione um projeto para abrir o terminal.");
        return;
      }
      try {
        const s = await post<{ session_id: string }>("/api/agent/sessions", {
          project,
          task: "Sessão do Terminal Interativo",
          mode: "auto",
        });
        targetSessionId = s.session_id;
        onSessionCreated?.(s.session_id);
      } catch (err) {
        setEstado("erro");
        setDetalhe("Falha ao inicializar o sandbox do terminal.");
        return;
      }
    }

    let ticket: string;
    try {
      const r = await post<{ ticket: string }>(`/api/workspace/terminal/${targetSessionId}/ticket`);
      ticket = r.ticket;
    } catch (err) {
      setEstado("erro");
      setDetalhe(err instanceof Error ? err.message : String(err));
      return;
    }

    const origem =
      process.env.NEXT_PUBLIC_API_ORIGIN ?? `${window.location.protocol}//${window.location.hostname}:5401`;
    const url = `${origem.replace(/^http/, "ws")}/api/workspace/terminal/${targetSessionId}?ticket=${encodeURIComponent(ticket)}`;

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onmessage = (event) => {
      const term = termRef.current;
      if (!term) return;
      const dados = JSON.parse(event.data as string);

      if (dados.type === "ready") {
        setEstado("pronto");
        term.writeln("\x1b[90mconectado ao sandbox · /workspace\x1b[0m");
        term.write(PROMPT);
      } else if (dados.type === "started") {
        term.writeln("");
      } else if (dados.type === "output") {
        if (dados.stdout) term.write(String(dados.stdout).replace(/\n/g, "\r\n"));
        if (dados.stderr) term.write(`\x1b[31m${String(dados.stderr).replace(/\n/g, "\r\n")}\x1b[0m`);
        if (dados.exit_code !== 0) {
          term.writeln(`\r\n\x1b[33m[saída ${dados.exit_code}]\x1b[0m`);
        }
        term.write(`\r\n${PROMPT}`);
      } else if (dados.type === "error") {
        term.writeln(`\r\n\x1b[31m${dados.message}\x1b[0m`);
        setDetalhe(String(dados.message));
      }
    };

    socket.onclose = () => {
      socketRef.current = null;
      setEstado("parado");
      termRef.current?.writeln("\r\n\x1b[90mconexão encerrada\x1b[0m");
    };
    socket.onerror = () => {
      setEstado("erro");
      setDetalhe("falha na conexão do WebSocket");
    };
  }, [sessionId]);

  useEffect(() => {
    let disposed = false;
    let fit: import("@xterm/addon-fit").FitAddon | null = null;

    // O xterm toca `window` na importação, então só pode carregar no cliente.
    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed || !containerRef.current) return;

      const term = new Terminal({
        fontSize: 12,
        fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
        theme: { background: "#0b0d10", foreground: "#e6e9ee", cursor: "#4ade80" },
        cursorBlink: true,
        convertEol: true,
      });
      fit = new FitAddon();
      term.loadAddon(fit);
      term.open(containerRef.current);
      fit.fit();
      termRef.current = term;

      term.writeln("\x1b[90mInicie uma sessão de agente para abrir um sandbox.\x1b[0m");

      term.onData((data) => {
        const socket = socketRef.current;
        if (!socket || socket.readyState !== WebSocket.OPEN) return;

        if (data === "\r") {
          const comando = bufferRef.current.trim();
          bufferRef.current = "";
          if (comando) socket.send(JSON.stringify({ command: comando }));
          else term.write(`\r\n${PROMPT}`);
        } else if (data === "\x7f" || data === "\b") {
          if (bufferRef.current) {
            bufferRef.current = bufferRef.current.slice(0, -1);
            term.write("\b \b");
          }
        } else if (data >= " ") {
          bufferRef.current += data;
          term.write(data);
        }
      });
    })();

    const onResize = () => fit?.fit();
    window.addEventListener("resize", onResize);

    return () => {
      disposed = true;
      window.removeEventListener("resize", onResize);
      socketRef.current?.close();
      socketRef.current = null;
      termRef.current?.dispose();
      termRef.current = null;
    };
  }, []);

  useEffect(() => {
    void conectar();
  }, [sessionId, project, conectar]);

  const [aba, setAba] = useState<"terminal" | "debugger">("terminal");

  const enviarComando = useCallback((cmd: string) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    termRef.current?.write(`${cmd}\r\n`);
    socket.send(JSON.stringify({ command: cmd }));

    // ✅ INTEGRAÇÃO TERMINAL IDE <-> AUDITORIA
    try {
      const { LocalDB } = require("@/lib/db");
      LocalDB.addAuditLog({
        actor: "Desenvolvedor (Terminal Sandbox)",
        module: "IDE",
        action: "Execução de Comando no Terminal",
        details: `Executado comando "${cmd}" no projeto "${project || "desconhecido"}".`,
        riskLevel: cmd.includes("rm") || cmd.includes("delete") ? "high" : "low",
        ipAddress: "127.0.0.1",
        status: "success",
      });
    } catch {
      // Ignora erro se DB indisponível
    }
  }, [project]);

  useEffect(() => {
    const handleCustomExec = (e: Event) => {
      const customEvt = e as CustomEvent<{ command: string }>;
      if (customEvt.detail?.command) {
        enviarComando(customEvt.detail.command);
      }
    };
    window.addEventListener("sicoobito:terminal:exec", handleCustomExec);
    return () => window.removeEventListener("sicoobito:terminal:exec", handleCustomExec);
  }, [enviarComando]);

  return (
    <div className="terminal-panel">
      <div className="terminal-bar">
        <div className="terminal-tabs">
          <button
            type="button"
            className={`terminal-tab ${aba === "terminal" ? "active" : ""}`}
            onClick={() => setAba("terminal")}
          >
            💻 Terminal Interativo
          </button>
          <button
            type="button"
            className={`terminal-tab ${aba === "debugger" ? "active" : ""}`}
            onClick={() => setAba("debugger")}
          >
            🐞 Saída & Debugger
          </button>
        </div>

        <span className={`pill ${estado === "pronto" ? "ok" : estado === "erro" ? "bad" : ""}`}>
          {estado}
        </span>
        {detalhe && <span className="terminal-detail">{detalhe}</span>}

        <div className="terminal-quick-cmds" style={{ marginLeft: "auto", display: "flex", gap: 4, flexWrap: "wrap" }}>
          <button
            type="button"
            className="term-chip glow-chip"
            onClick={() => enviarComando("npm run dev")}
            disabled={estado !== "pronto"}
            title="Iniciar servidor de desenvolvimento"
          >
            🚀 Dev Server
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => enviarComando("python -m pytest")}
            disabled={estado !== "pronto"}
            title="Executar testes automatizados"
          >
            ▶ Rodar Testes
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => enviarComando("git status")}
            disabled={estado !== "pronto"}
            title="Verificar estado do git"
          >
            git status
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => enviarComando("git diff")}
            disabled={estado !== "pronto"}
            title="Verificar alterações no git"
          >
            git diff
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => termRef.current?.clear()}
            title="Limpar terminal"
          >
            🧹 Limpar
          </button>
        </div>
      </div>

      <div
        className="terminal-surface"
        ref={containerRef}
        style={{ display: aba === "terminal" ? "block" : "none" }}
      />

      {aba === "debugger" && (
        <div style={{ padding: "12px", background: "#0b0d10", color: "#4ade80", fontFamily: "monospace", fontSize: "12px", height: "100%", overflowY: "auto" }}>
          <div>[DEBUGGER] Console de Saída e Rastreio do Agente</div>
          <div style={{ color: "#94a3b8", marginTop: "4px" }}>
            - Sessão de execução ativa: {sessionId ?? "nenhuma sessão selecionada"}
          </div>
          <div style={{ color: "#94a3b8" }}>
            - Estado do Sandbox: {estado === "pronto" ? "Conectado e operacional" : "Aguardando inicialização..."}
          </div>
          <div style={{ marginTop: "12px", color: "#e2e8f0", borderTop: "1px solid #1e293b", paddingTop: "8px" }}>
            Execute comandos no terminal interativo acima para visualizar a saída bruta e códigos de erro de execução.
          </div>
        </div>
      )}
    </div>
  );
}
