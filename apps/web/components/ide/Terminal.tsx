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

export function TerminalPanel({ sessionId }: { sessionId: string | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<import("@xterm/xterm").Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const bufferRef = useRef("");
  const [estado, setEstado] = useState<"parado" | "conectando" | "pronto" | "erro">("parado");
  const [detalhe, setDetalhe] = useState<string | null>(null);

  const conectar = useCallback(async () => {
    if (!sessionId || socketRef.current) return;
    setEstado("conectando");
    setDetalhe(null);

    let ticket: string;
    try {
      const r = await post<{ ticket: string }>(`/api/workspace/terminal/${sessionId}/ticket`);
      ticket = r.ticket;
    } catch (err) {
      setEstado("erro");
      setDetalhe(err instanceof Error ? err.message : String(err));
      return;
    }

    // O WebSocket não passa pelo proxy do Next: o browser abre direto na API.
    const origem =
      process.env.NEXT_PUBLIC_API_ORIGIN ?? `${window.location.protocol}//${window.location.hostname}:5401`;
    const url = `${origem.replace(/^http/, "ws")}/api/workspace/terminal/${sessionId}?ticket=${encodeURIComponent(ticket)}`;

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
    if (sessionId) void conectar();
  }, [sessionId, conectar]);

  const enviarComando = (cmd: string) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    termRef.current?.write(cmd);
    socket.send(JSON.stringify({ command: cmd }));
  };

  return (
    <div className="terminal-panel">
      <div className="terminal-bar">
        <div className="terminal-tabs">
          <button type="button" className="terminal-tab active">
            💻 Terminal (Sandbox)
          </button>
        </div>

        <span className={`pill ${estado === "pronto" ? "ok" : estado === "erro" ? "bad" : ""}`}>
          {estado}
        </span>
        {detalhe && <span className="terminal-detail">{detalhe}</span>}

        <div className="terminal-quick-cmds" style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          <button
            type="button"
            className="term-chip"
            onClick={() => enviarComando("npm run build")}
            disabled={estado !== "pronto"}
            title="Executar npm run build"
          >
            build
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => enviarComando("pytest")}
            disabled={estado !== "pronto"}
            title="Executar testes com pytest"
          >
            pytest
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => enviarComando("git status")}
            disabled={estado !== "pronto"}
            title="Executar git status"
          >
            git status
          </button>
          <button
            type="button"
            className="term-chip"
            onClick={() => termRef.current?.clear()}
            title="Limpar tela"
          >
            clear
          </button>
        </div>
      </div>
      <div className="terminal-surface" ref={containerRef} />
    </div>
  );
}
