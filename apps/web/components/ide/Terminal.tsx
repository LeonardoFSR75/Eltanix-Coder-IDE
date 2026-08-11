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
import { logAuditEvent } from "@/lib/api/audit";
import { useTheme } from "@/lib/theme";

const PROMPT = "\x1b[32m$\x1b[0m ";

export function TerminalPanel({
  sessionId,
  project,
  onSessionCreated,
  onClose,
}: {
  sessionId: string | null;
  project?: string | null;
  onSessionCreated?: (id: string) => void;
  onClose?: () => void;
}) {
  const { theme } = useTheme();
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
  }, [sessionId, project, onSessionCreated]);

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
        theme: {
          background: theme === "light" ? "#ffffff" : "#0b0d10",
          foreground: theme === "light" ? "#0f172a" : "#e6e9ee",
          cursor: theme === "light" ? "#0284c7" : "#4ade80",
        },
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

    const observer = new ResizeObserver(() => fit?.fit());
    if (containerRef.current) observer.observe(containerRef.current);
    const onResize = () => fit?.fit();
    window.addEventListener("resize", onResize);

    return () => {
      disposed = true;
      observer.disconnect();
      window.removeEventListener("resize", onResize);
      socketRef.current?.close();
      socketRef.current = null;
      termRef.current?.dispose();
      termRef.current = null;
    };
  }, []);

  useEffect(() => {
    // A guarda no topo de `conectar` (`if (socketRef.current) return`) existe
    // para não abrir duas conexões em paralelo, mas isso também bloqueava
    // reconectar quando `sessionId`/`project` mudam com uma conexão antiga
    // ainda aberta: comandos digitados continuavam indo para o sandbox da
    // sessão/projeto anterior, sem aviso nenhum. Fechar aqui antes de chamar
    // `conectar()` de novo garante que a troca sempre reconecta no alvo certo.
    socketRef.current?.close();
    socketRef.current = null;
    void conectar();
  }, [sessionId, project, conectar]);

  const [aba, setAba] = useState<"terminal" | "debugger">("terminal");

  const enviarComando = useCallback((cmd: string) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    termRef.current?.write(`${cmd}\r\n`);
    socket.send(JSON.stringify({ command: cmd }));

    logAuditEvent({
      actor: "Desenvolvedor (Terminal Sandbox)",
      module: "IDE",
      action: "Execução de Comando no Terminal",
      details: `Executado comando "${cmd}" no projeto "${project || "desconhecido"}".`,
      risk_level: cmd.includes("rm") || cmd.includes("delete") ? "critical" : "low",
      status: "success",
    }).catch(() => {});
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
            <span>💻</span> Terminal
          </button>
          <button
            type="button"
            className={`terminal-tab ${aba === "debugger" ? "active" : ""}`}
            onClick={() => setAba("debugger")}
          >
            <span>🐞</span> Debugger
          </button>
        </div>

        <div className="terminal-status-wrap">
          <span className={`terminal-status-dot ${estado === "pronto" ? "ok" : estado === "erro" ? "err" : "loading"}`} />
          <span>{estado}</span>
        </div>

        <div className="terminal-actions-right">
          <div className="terminal-quick-cmds">
            <button
              type="button"
              className="term-chip"
              onClick={() => enviarComando("npm run dev")}
              disabled={estado !== "pronto"}
              title="Iniciar servidor de desenvolvimento (npm run dev)"
            >
              🚀 Dev
            </button>
            <button
              type="button"
              className="term-chip"
              onClick={() => enviarComando("python -m pytest")}
              disabled={estado !== "pronto"}
              title="Executar testes automatizados (pytest)"
            >
              ▶ Testes
            </button>
            <button
              type="button"
              className="term-chip"
              onClick={() => enviarComando("git status")}
              disabled={estado !== "pronto"}
              title="Verificar estado do Git (git status)"
            >
              git status
            </button>
          </div>

          <div className="terminal-bar-divider" />

          <button
            type="button"
            className="terminal-icon-btn"
            onClick={() => termRef.current?.clear()}
            title="Limpar saída do terminal"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>

          {onClose && (
            <button
              type="button"
              className="terminal-icon-btn terminal-minimize-btn"
              onClick={onClose}
              title="Minimizar gaveta do terminal (Ctrl+`)"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          )}
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
