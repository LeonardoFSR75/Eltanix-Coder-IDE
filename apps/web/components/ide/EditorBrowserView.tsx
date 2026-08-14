"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { browserAction, closeBrowserSession } from "@/lib/api/browser";
import { useIde } from "@/lib/ide-store";

interface EditorBrowserViewProps {
  initialUrl?: string;
  sessionId?: string;
}

export function EditorBrowserView({
  initialUrl = "http://localhost:5000",
  sessionId: customSessionId,
}: EditorBrowserViewProps) {
  const { activeSessionId } = useIde();
  const rawSessionId = customSessionId || activeSessionId || "ide-main-browser";
  const sessionId = rawSessionId;

  const [urlInput, setUrlInput] = useState(initialUrl);
  const [currentUrl, setCurrentUrl] = useState<string | null>(initialUrl);
  const [title, setTitle] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [clickIndicator, setClickIndicator] = useState<{ x: number; y: number } | null>(null);
  const [showInspector, setShowInspector] = useState(false);
  const [selectorInput, setSelectorInput] = useState("");
  const [textInput, setTextInput] = useState("");

  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const capturar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const shot = await browserAction({ sessionId, action: "screenshot" });
      if (shot.image_base64) {
        setImage(shot.image_base64);
      }
      if (shot.url) setCurrentUrl(shot.url);
      if (shot.title) setTitle(shot.title);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const navegar = useCallback(
    async (destino: string) => {
      const bruto = destino.trim();
      if (!bruto) return;
      const alvo = /^https?:\/\//i.test(bruto) ? bruto : `http://${bruto}`;
      setLoading(true);
      setErro(null);
      setContent(null);
      try {
        const resultado = await browserAction({ sessionId, action: "navigate", url: alvo });
        const finalUrl = resultado.url ?? alvo;
        setCurrentUrl(finalUrl);
        setUrlInput(finalUrl);
        setTitle(resultado.title ?? null);
        setStatus(resultado.status ?? 200);
        setDurationMs(resultado.duration_ms ?? null);
        if (resultado.image_base64) {
          setImage(resultado.image_base64);
        } else {
          await capturar();
        }
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [sessionId, capturar],
  );

  useEffect(() => {
    if (initialUrl) {
      void navegar(initialUrl);
    }
  }, [initialUrl, navegar]);

  const clicarNaCaptura = useCallback(
    async (e: React.MouseEvent<HTMLImageElement>) => {
      if (!imgRef.current || loading) return;
      const img = imgRef.current;
      const rect = img.getBoundingClientRect();
      const scaleX = img.naturalWidth / rect.width;
      const scaleY = img.naturalHeight / rect.height;
      const x = Math.round((e.clientX - rect.left) * scaleX);
      const y = Math.round((e.clientY - rect.top) * scaleY);

      setClickIndicator({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      setTimeout(() => setClickIndicator(null), 600);

      setLoading(true);
      setErro(null);
      try {
        await browserAction({ sessionId, action: "click", x, y });
        await new Promise((r) => setTimeout(r, 300));
        await capturar();
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [sessionId, loading, capturar],
  );

  const enviarTexto = useCallback(async () => {
    if (!selectorInput.trim() || !textInput) return;
    setLoading(true);
    setErro(null);
    try {
      await browserAction({
        sessionId,
        action: "type",
        selector: selectorInput.trim(),
        text: textInput,
      });
      await new Promise((r) => setTimeout(r, 300));
      await capturar();
      setTextInput("");
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sessionId, selectorInput, textInput, capturar]);

  const verConteudo = useCallback(async () => {
    setErro(null);
    try {
      const resultado = await browserAction({ sessionId, action: "content" });
      setContent(resultado.text ?? "");
      setShowInspector(true);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  }, [sessionId]);

  const reiniciar = useCallback(async () => {
    try {
      await closeBrowserSession(sessionId);
    } catch {
      // Ignora erro se sessão já foi fechada
    }
    setImage(null);
    setContent(null);
    setTitle(null);
    setStatus(null);
    setErro(null);
  }, [sessionId]);

  return (
    <div className="editor-browser-container" ref={containerRef}>
      {/* Barra de Endereços e Controles */}
      <div className="editor-browser-header">
        <div className="editor-browser-nav-group">
          <button
            type="button"
            className="editor-browser-btn"
            title="Recarregar página"
            onClick={() => currentUrl && void navegar(currentUrl)}
            disabled={loading || !currentUrl}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
        </div>

        <div className="editor-browser-url-bar">
          <span className="editor-browser-url-icon">🌐</span>
          <input
            type="text"
            className="editor-browser-url-input"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void navegar(urlInput)}
            placeholder="http://localhost:5000"
          />
          <button
            type="button"
            className="editor-browser-go-btn"
            onClick={() => void navegar(urlInput)}
            disabled={loading || !urlInput.trim()}
          >
            {loading ? "Carregando…" : "Ir"}
          </button>
        </div>

        <div className="editor-browser-meta-group">
          {status && (
            <span className={`editor-browser-status-badge status-${status < 400 ? "ok" : "err"}`}>
              {status} OK
            </span>
          )}
          {durationMs !== null && (
            <span className="editor-browser-duration-badge">{durationMs}ms</span>
          )}
          <button
            type="button"
            className={`editor-browser-tool-btn ${showInspector ? "active" : ""}`}
            title="Inspecionar texto e formulários"
            onClick={() => setShowInspector((p) => !p)}
          >
            Inspecionar
          </button>
          <button
            type="button"
            className="editor-browser-tool-btn"
            title="Reiniciar sessão do navegador"
            onClick={() => void reiniciar()}
          >
            Reiniciar
          </button>
        </div>
      </div>

      {erro && (
        <div className="editor-browser-error-banner">
          <span>⚠️ {erro}</span>
        </div>
      )}

      {/* Viewport Principal Grande */}
      <div className="editor-browser-viewport-wrapper">
        <div className="editor-browser-viewport">
          {image ? (
            <div className="editor-browser-screen-frame">
              <img
                ref={imgRef}
                src={`data:image/png;base64,${image}`}
                alt={title || currentUrl || "Página renderizada"}
                className="editor-browser-screen-img"
                onClick={(e) => void clicarNaCaptura(e)}
                title="Clique em qualquer elemento para interagir"
              />
              {clickIndicator && (
                <div
                  className="editor-browser-click-ripple"
                  style={{ left: clickIndicator.x, top: clickIndicator.y }}
                />
              )}
            </div>
          ) : (
            <div className="editor-browser-empty-state">
              <div className="editor-browser-empty-icon">🌐</div>
              <h3>Navegador Headless Playwright</h3>
              <p>Digite uma URL acima ou aguarde o agente abrir uma aplicação web.</p>
              <button
                type="button"
                className="theme-btn primary"
                onClick={() => void navegar(urlInput || "http://localhost:5000")}
              >
                Abrir http://localhost:5000
              </button>
            </div>
          )}
        </div>

        {/* Gaveta de Inspeção / Digitação */}
        {showInspector && (
          <div className="editor-browser-inspector-drawer">
            <div className="editor-browser-inspector-header">
              <span>Painel de Interação & Diagnóstico</span>
              <button
                type="button"
                className="editor-browser-close-btn"
                onClick={() => setShowInspector(false)}
              >
                ×
              </button>
            </div>

            <div className="editor-browser-inspector-body">
              <div className="editor-browser-type-section">
                <span className="inspector-section-title">Digitar em Campo / Input:</span>
                <div className="inspector-type-inputs">
                  <input
                    type="text"
                    placeholder="Seletor CSS (ex.: #nome, input[name='aluno'])"
                    value={selectorInput}
                    onChange={(e) => setSelectorInput(e.target.value)}
                    className="inspector-input"
                  />
                  <input
                    type="text"
                    placeholder="Texto para digitar..."
                    value={textInput}
                    onChange={(e) => setTextInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && void enviarTexto()}
                    className="inspector-input"
                  />
                  <button
                    type="button"
                    className="theme-btn primary"
                    onClick={() => void enviarTexto()}
                    disabled={loading || !selectorInput.trim() || !textInput}
                  >
                    Digitar
                  </button>
                </div>
              </div>

              <div className="editor-browser-content-section">
                <div className="inspector-content-bar">
                  <span className="inspector-section-title">Texto Extraído da Página:</span>
                  <button
                    type="button"
                    className="theme-btn"
                    onClick={() => void verConteudo()}
                    disabled={loading || !currentUrl}
                  >
                    Recarregar Texto
                  </button>
                </div>
                {content ? (
                  <pre className="inspector-content-pre">{content}</pre>
                ) : (
                  <p className="inspector-empty-hint">Clique em &quot;Recarregar Texto&quot; para ler o DOM da página.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
