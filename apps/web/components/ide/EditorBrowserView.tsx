"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  browserAction,
  buildBrowserStreamUrl,
  closeBrowserSession,
  getBrowserNetworkLog,
  getBrowserReplay,
  getBrowserStreamTicket,
  type NetworkLogEntry,
  type ReplayDetail,
} from "@/lib/api/browser";
import { getSandboxServerLogs, getSandboxStats, type SandboxStats } from "@/lib/api/sandbox";
import { HttpError } from "@/lib/client";
import { useIde } from "@/lib/ide-store";

import { BrowserReplayPanel } from "./BrowserReplayPanel";

export type ViewportMode = "responsive" | "desktop" | "laptop" | "tablet" | "mobile" | "mobile-max";
export type RenderMode = "live" | "headless";

interface BrowserTab {
  id: string;
  title: string;
  url: string;
  mode: RenderMode;
  history: string[];
  historyIndex: number;
}

interface EditorBrowserViewProps {
  initialUrl?: string;
  sessionId?: string;
  isStandalone?: boolean;
}

const VIEWPORT_SIZES: Record<ViewportMode, { width: string; height?: string; label: string; icon: string }> = {
  responsive: { width: "100%", label: "Responsivo (100%)", icon: "🖥️" },
  desktop: { width: "1280px", label: "Desktop (1280px)", icon: "💻" },
  laptop: { width: "1024px", label: "Laptop (1024px)", icon: "💻" },
  tablet: { width: "768px", height: "1024px", label: "Tablet (768x1024)", icon: "📟" },
  mobile: { width: "375px", height: "667px", label: "Mobile SE (375x667)", icon: "📱" },
  "mobile-max": { width: "390px", height: "844px", label: "Mobile Max (390x844)", icon: "📲" },
};

const DEV_BOOKMARKS = [
  { label: ":3000 Next.js", url: "http://localhost:3000" },
  { label: ":5173 Vite", url: "http://localhost:5173" },
  { label: ":8000 Swagger", url: "http://localhost:8000/docs" },
  { label: ":5000 API", url: "http://localhost:5000" },
  { label: ":8080 App", url: "http://localhost:8080" },
];

export function EditorBrowserView({
  initialUrl = "http://localhost:3000",
  sessionId: customSessionId,
  isStandalone = false,
}: EditorBrowserViewProps) {
  const { activeSessionId } = useIde();
  const rawSessionId = customSessionId || activeSessionId || "ide-main-browser";
  const sessionId = rawSessionId;

  // Gerenciamento de Múltiplas Abas
  const [tabs, setTabs] = useState<BrowserTab[]>([
    {
      id: "tab-1",
      title: "Localhost",
      url: initialUrl,
      mode: "live",
      history: [initialUrl],
      historyIndex: 0,
    },
  ]);
  const [activeTabId, setActiveTabId] = useState<string>("tab-1");

  const currentTab = tabs.find((t) => t.id === activeTabId) || tabs[0];

  const [urlInput, setUrlInput] = useState(currentTab.url);
  const [currentUrl, setCurrentUrl] = useState<string | null>(currentTab.url);
  const [title, setTitle] = useState<string | null>(currentTab.title);
  const [renderMode, setRenderMode] = useState<RenderMode>(currentTab.mode);

  const [status, setStatus] = useState<number | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [consoleErrors, setConsoleErrors] = useState<string[]>([]);
  const [pageErrors, setPageErrors] = useState<string[]>([]);
  const [clickIndicator, setClickIndicator] = useState<{ x: number; y: number } | null>(null);

  // Responsividade & Fullscreen
  const [viewportMode, setViewportMode] = useState<ViewportMode>("responsive");
  const [isLandscape, setIsLandscape] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [zoomLevel, setZoomLevel] = useState<number>(100);

  // DevTools & Drawer
  const [showDrawer, setShowDrawer] = useState(false);
  const [drawerTab, setDrawerTab] = useState<"inspector" | "logs" | "network" | "replay">("logs");
  const [serverLogs, setServerLogs] = useState("");
  const [networkLog, setNetworkLog] = useState<NetworkLogEntry[]>([]);
  const [replayData, setReplayData] = useState<ReplayDetail | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [replayRefreshKey, setReplayRefreshKey] = useState(0);
  const [sandboxStats, setSandboxStats] = useState<SandboxStats | null>(null);
  const [selectorInput, setSelectorInput] = useState("");
  const [textInput, setTextInput] = useState("");

  // Streaming ao vivo (CDP screencast) no modo Agente
  const [streamActive, setStreamActive] = useState(false);
  const [streamConnecting, setStreamConnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const streamFrameImgRef = useRef<HTMLImageElement>(new Image());

  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Sincroniza estado da URL quando a aba ativa muda
  useEffect(() => {
    if (currentTab) {
      setUrlInput(currentTab.url);
      setCurrentUrl(currentTab.url);
      setTitle(currentTab.title);
      setRenderMode(currentTab.mode);
    }
  }, [activeTabId]);

  // Listener para estado Fullscreen nativo
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await containerRef.current.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch (err) {
      console.warn("Fullscreen toggle failed:", err);
    }
  }, []);

  // Atalho de teclado F11 para tela cheia dentro do browser
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "F11") {
        e.preventDefault();
        void toggleFullscreen();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleFullscreen]);

  // Captura de tela via Headless
  const capturar = useCallback(async () => {
    if (renderMode === "live") return;
    setLoading(true);
    setErro(null);
    try {
      const shot = await browserAction({ sessionId, action: "screenshot" });
      if (shot.image_base64) {
        setImage(shot.image_base64);
      }
      if (shot.url) setCurrentUrl(shot.url);
      if (shot.title) setTitle(shot.title);
      setConsoleErrors(shot.console_errors ?? []);
      setPageErrors(shot.page_errors ?? []);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sessionId, renderMode]);

  // Streaming ao vivo — só faz sentido no modo Agente (headless/CDP); no modo
  // Live o iframe já é a própria fonte visual, sem precisar de screencast.
  const pararStream = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setStreamActive(false);
    setStreamConnecting(false);
  }, []);

  const iniciarStream = useCallback(async () => {
    if (renderMode !== "headless" || wsRef.current) return;
    setStreamConnecting(true);
    setErro(null);
    try {
      const { ticket } = await getBrowserStreamTicket(sessionId);
      const url = buildBrowserStreamUrl(sessionId, ticket);
      const socket = new WebSocket(url);
      wsRef.current = socket;

      socket.onopen = () => {
        setStreamConnecting(false);
        setStreamActive(true);
      };

      socket.onmessage = (evento) => {
        try {
          const msg = JSON.parse(evento.data as string) as { type: string; data?: string };
          if (msg.type !== "frame" || !msg.data) return;
          const img = streamFrameImgRef.current;
          img.onload = () => {
            const canvas = canvasRef.current;
            if (!canvas) return;
            if (canvas.width !== img.naturalWidth || canvas.height !== img.naturalHeight) {
              canvas.width = img.naturalWidth;
              canvas.height = img.naturalHeight;
            }
            canvas.getContext("2d")?.drawImage(img, 0, 0);
          };
          img.src = `data:image/jpeg;base64,${msg.data}`;
        } catch {
          // Frame malformado — ignora, o próximo chega em instantes.
        }
      };

      socket.onerror = () => {
        setErro("falha na conexão de streaming ao vivo");
      };

      socket.onclose = () => {
        wsRef.current = null;
        setStreamActive(false);
        setStreamConnecting(false);
      };
    } catch (err) {
      setStreamConnecting(false);
      setErro(err instanceof Error ? err.message : String(err));
    }
  }, [sessionId, renderMode]);

  // Encerra o stream ao desmontar ou ao sair do modo Agente/trocar de sessão.
  useEffect(() => {
    if (renderMode !== "headless" && wsRef.current) pararStream();
  }, [renderMode, pararStream]);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [sessionId]);

  // Navegar para nova URL
  const navegar = useCallback(
    async (destino: string, pushHistory = true) => {
      const bruto = destino.trim();
      if (!bruto) return;
      const alvo = /^https?:\/\//i.test(bruto) ? bruto : `http://${bruto}`;

      setLoading(true);
      setErro(null);
      setContent(null);

      // Atualiza estado da aba atual
      setTabs((prev) =>
        prev.map((t) => {
          if (t.id !== activeTabId) return t;
          let newHistory = t.history;
          let newIndex = t.historyIndex;
          if (pushHistory && t.url !== alvo) {
            newHistory = [...t.history.slice(0, t.historyIndex + 1), alvo];
            newIndex = newHistory.length - 1;
          }
          return {
            ...t,
            url: alvo,
            title: alvo.replace(/^https?:\/\//i, ""),
            history: newHistory,
            historyIndex: newIndex,
          };
        }),
      );

      setCurrentUrl(alvo);
      setUrlInput(alvo);

      if (renderMode === "live") {
        if (iframeRef.current) {
          iframeRef.current.src = alvo;
        }
        setLoading(false);
        return;
      }

      try {
        const resultado = await browserAction({ sessionId, action: "navigate", url: alvo });
        const finalUrl = resultado.url ?? alvo;
        setCurrentUrl(finalUrl);
        setUrlInput(finalUrl);
        setTitle(resultado.title ?? null);
        setStatus(resultado.status ?? 200);
        setDurationMs(resultado.duration_ms ?? null);
        setConsoleErrors(resultado.console_errors ?? []);
        setPageErrors(resultado.page_errors ?? []);
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
    [sessionId, capturar, renderMode, activeTabId],
  );

  // Navegação de Histórico (Voltar / Avançar)
  const voltar = useCallback(() => {
    if (currentTab.historyIndex > 0) {
      const prevUrl = currentTab.history[currentTab.historyIndex - 1];
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTabId ? { ...t, historyIndex: t.historyIndex - 1, url: prevUrl } : t,
        ),
      );
      void navegar(prevUrl, false);
    }
  }, [currentTab, activeTabId, navegar]);

  const avancar = useCallback(() => {
    if (currentTab.historyIndex < currentTab.history.length - 1) {
      const nextUrl = currentTab.history[currentTab.historyIndex + 1];
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTabId ? { ...t, historyIndex: t.historyIndex + 1, url: nextUrl } : t,
        ),
      );
      void navegar(nextUrl, false);
    }
  }, [currentTab, activeTabId, navegar]);

  const recarregar = useCallback(() => {
    if (currentUrl) {
      if (renderMode === "live" && iframeRef.current) {
        iframeRef.current.src = currentUrl;
      } else {
        void navegar(currentUrl, false);
      }
    }
  }, [currentUrl, renderMode, navegar]);

  const irParaHome = useCallback(() => {
    void navegar(initialUrl);
  }, [initialUrl, navegar]);

  // Gestão de Abas
  const adicionarAba = useCallback(() => {
    const newId = `tab-${Date.now()}`;
    const newTab: BrowserTab = {
      id: newId,
      title: "Nova Aba",
      url: "http://localhost:3000",
      mode: "live",
      history: ["http://localhost:3000"],
      historyIndex: 0,
    };
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newId);
  }, []);

  const fecharAba = useCallback(
    (tabId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (tabs.length === 1) return;
      const filtered = tabs.filter((t) => t.id !== tabId);
      setTabs(filtered);
      if (activeTabId === tabId) {
        setActiveTabId(filtered[filtered.length - 1].id);
      }
    },
    [tabs, activeTabId],
  );

  // Polling de telemetria e stats do container do Sandbox
  useEffect(() => {
    let ativo = true;
    const targetSid = sessionId || activeSessionId;
    if (!targetSid) return;
    const fetchStats = async () => {
      try {
        const data = await getSandboxStats(targetSid);
        if (ativo && data) setSandboxStats(data);
      } catch {
        // Ignora erros de polling
      }
    };
    void fetchStats();
    const timer = setInterval(fetchStats, 4000);
    return () => {
      ativo = false;
      clearInterval(timer);
    };
  }, [sessionId, activeSessionId]);

  // Polling de logs do servidor quando o drawer de logs estiver aberto
  useEffect(() => {
    const targetSid = sessionId || activeSessionId;
    if (!showDrawer || drawerTab !== "logs" || !targetSid) return;
    let ativo = true;
    const fetchLogs = async () => {
      try {
        const data = await getSandboxServerLogs(targetSid, 200);
        if (ativo && data?.logs) {
          setServerLogs(data.logs);
        }
      } catch {
        // Ignora erros
      }
    };
    void fetchLogs();
    const timer = setInterval(fetchLogs, 2500);
    return () => {
      ativo = false;
      clearInterval(timer);
    };
  }, [showDrawer, drawerTab, sessionId, activeSessionId]);

  // Polling do log de rede quando o drawer estiver na aba "Rede"
  useEffect(() => {
    if (!showDrawer || drawerTab !== "network") return;
    let ativo = true;
    const fetchNetwork = async () => {
      try {
        const data = await getBrowserNetworkLog(sessionId);
        if (ativo) setNetworkLog(data.requests ?? []);
      } catch {
        // Ignora erros
      }
    };
    void fetchNetwork();
    const timer = setInterval(fetchNetwork, 2000);
    return () => {
      ativo = false;
      clearInterval(timer);
    };
  }, [showDrawer, drawerTab, sessionId]);

  // Busca o replay (trace + vídeo) quando a aba "Replay" é aberta — dado
  // estático depois que a sessão fecha (`reiniciar()`), não precisa de
  // polling como rede/logs.
  useEffect(() => {
    if (!showDrawer || drawerTab !== "replay") return;
    let ativo = true;
    setReplayLoading(true);
    setReplayError(null);
    getBrowserReplay(sessionId)
      .then((data) => {
        if (ativo) setReplayData(data);
      })
      .catch((err) => {
        if (!ativo) return;
        setReplayData(null);
        setReplayError(
          err instanceof HttpError && err.status === 404
            ? "Nenhum replay disponível ainda — feche a sessão (\"Reiniciar\") para gerar vídeo + trace."
            : err instanceof Error
              ? err.message
              : String(err),
        );
      })
      .finally(() => {
        if (ativo) setReplayLoading(false);
      });
    return () => {
      ativo = false;
    };
  }, [showDrawer, drawerTab, sessionId, replayRefreshKey]);

  // Ações interativas no modo Headless
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

  // Mesma ideia, mas para o modo de streaming ao vivo: o próximo frame do
  // screencast já mostra o resultado, então não precisa forçar `capturar()`.
  const clicarNoStream = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas || !canvas.width) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = Math.round((e.clientX - rect.left) * scaleX);
      const y = Math.round((e.clientY - rect.top) * scaleY);

      setClickIndicator({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      setTimeout(() => setClickIndicator(null), 600);

      void browserAction({ sessionId, action: "click", x, y }).catch((err) => {
        setErro(err instanceof Error ? err.message : String(err));
      });
    },
    [sessionId],
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
      setDrawerTab("inspector");
      setShowDrawer(true);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  }, [sessionId]);

  const reiniciar = useCallback(async () => {
    pararStream();
    try {
      await closeBrowserSession(sessionId);
    } catch {
      // Ignora erro
    }
    setImage(null);
    setContent(null);
    setTitle(null);
    setStatus(null);
    setErro(null);
    setConsoleErrors([]);
    setPageErrors([]);
    setNetworkLog([]);
    setReplayRefreshKey((k) => k + 1);
  }, [sessionId, pararStream]);

  const downloadScreenshot = useCallback(() => {
    if (!image) return;
    const a = document.createElement("a");
    a.href = `data:image/png;base64,${image}`;
    a.download = `screenshot-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
    a.click();
  }, [image]);

  const portasStr = sandboxStats?.ports?.length
    ? `Porta ${sandboxStats.ports.join(", ")}`
    : null;
  const memMb = sandboxStats?.metrics?.memory_mb;

  const canGoBack = currentTab.historyIndex > 0;
  const canGoForward = currentTab.historyIndex < currentTab.history.length - 1;
  const isSecure = currentUrl?.startsWith("https://");

  // Dimensões do viewport com suporte a rotação
  const currentViewport = VIEWPORT_SIZES[viewportMode];
  let viewportWidth = currentViewport.width;
  let viewportHeight = currentViewport.height || "100%";

  if (isLandscape && currentViewport.height) {
    viewportWidth = currentViewport.height;
    viewportHeight = currentViewport.width;
  }

  return (
    <div
      className={`editor-browser-container ${isFullscreen ? "browser-fullscreen-mode" : ""} ${isStandalone ? "browser-standalone-page" : ""}`}
      ref={containerRef}
    >
      {/* 📑 Barra Superior de Múltiplas Abas */}
      <div className="browser-tabs-bar">
        <div className="browser-tabs-list">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={`browser-tab-item ${tab.id === activeTabId ? "active" : ""}`}
              onClick={() => setActiveTabId(tab.id)}
            >
              <span className="browser-tab-icon">
                {tab.mode === "live" ? "⚡" : "🤖"}
              </span>
              <span className="browser-tab-title" title={tab.url}>
                {tab.title || tab.url.replace(/^https?:\/\//i, "")}
              </span>
              {tabs.length > 1 && (
                <button
                  type="button"
                  className="browser-tab-close"
                  onClick={(e) => fecharAba(tab.id, e)}
                  title="Fechar aba"
                >
                  ×
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="browser-add-tab-btn"
            onClick={adicionarAba}
            title="Abrir nova aba"
          >
            +
          </button>
        </div>

        {/* Controles de Janela / Fullscreen */}
        <div className="browser-window-controls">
          <button
            type="button"
            className={`editor-browser-btn ${isFullscreen ? "active" : ""}`}
            onClick={() => void toggleFullscreen()}
            title={isFullscreen ? "Sair da Tela Cheia (F11 / Esc)" : "Tela Cheia (F11)"}
          >
            {isFullscreen ? "🗗" : "⛶"}
          </button>
        </div>
      </div>

      {/* 🧭 Barra de Navegação Principal do Browser */}
      <div className="editor-browser-header">
        {/* Controles de Navegação (Voltar / Avançar / Recarregar / Home) */}
        <div className="editor-browser-nav-group">
          <button
            type="button"
            className="editor-browser-btn"
            title="Voltar (Alt + ←)"
            onClick={voltar}
            disabled={!canGoBack || loading}
          >
            ←
          </button>
          <button
            type="button"
            className="editor-browser-btn"
            title="Avançar (Alt + →)"
            onClick={avancar}
            disabled={!canGoForward || loading}
          >
            →
          </button>
          <button
            type="button"
            className={`editor-browser-btn ${loading ? "btn-spin" : ""}`}
            title="Recarregar página"
            onClick={recarregar}
            disabled={loading || !currentUrl}
          >
            🔄
          </button>
          <button
            type="button"
            className="editor-browser-btn"
            title="Ir para página inicial (Home)"
            onClick={irParaHome}
          >
            🏠
          </button>
        </div>

        {/* 🌐 Barra de Endereço URL com Protocolo */}
        <div className="editor-browser-url-bar">
          <span
            className="editor-browser-url-icon"
            title={isSecure ? "Conexão Segura HTTPS" : "Conexão Local / HTTP"}
          >
            {isSecure ? "🔒" : "🔓"}
          </span>
          <input
            type="text"
            className="editor-browser-url-input"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void navegar(urlInput)}
            placeholder="http://localhost:3000"
          />
          <button
            type="button"
            className="editor-browser-go-btn"
            onClick={() => void navegar(urlInput)}
            disabled={loading || !urlInput.trim()}
          >
            {loading ? "…" : "Ir"}
          </button>
          {currentUrl && (
            <a
              href={currentUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="browser-open-external-btn"
              title="Abrir em nova janela do sistema"
            >
              ↗
            </a>
          )}
        </div>

        {/* 🛠️ Controles de Modo de Renderização (Live vs Headless) */}
        <div className="browser-mode-switcher">
          <button
            type="button"
            className={`browser-mode-btn ${renderMode === "live" ? "active" : ""}`}
            onClick={() => {
              setRenderMode("live");
              setTabs((prev) =>
                prev.map((t) => (t.id === activeTabId ? { ...t, mode: "live" } : t)),
              );
            }}
            title="Modo Live Iframe (Interação nativa, HMR e WebSockets em tempo real)"
          >
            ⚡ Live
          </button>
          <button
            type="button"
            className={`browser-mode-btn ${renderMode === "headless" ? "active" : ""}`}
            onClick={() => {
              setRenderMode("headless");
              setTabs((prev) =>
                prev.map((t) => (t.id === activeTabId ? { ...t, mode: "headless" } : t)),
              );
              if (currentUrl) void navegar(currentUrl);
            }}
            title="Modo Headless Agent (Playwright / Lightpanda CDP com telemetria e inspeção)"
          >
            🤖 Agente
          </button>
          {renderMode === "headless" && (
            <button
              type="button"
              className={`browser-mode-btn ${streamActive ? "active" : ""}`}
              onClick={() => (streamActive ? pararStream() : void iniciarStream())}
              disabled={streamConnecting}
              title="Streaming ao vivo via CDP screencast (em vez de screenshot sob pedido)"
            >
              {streamConnecting ? "…" : streamActive ? "⏸ Ao Vivo" : "▶ Ao Vivo"}
            </button>
          )}
        </div>

        {/* 📱 Seletor de Viewport / Emulador de Dispositivo */}
        <div className="browser-viewport-selector">
          <select
            className="browser-viewport-select"
            value={viewportMode}
            onChange={(e) => setViewportMode(e.target.value as ViewportMode)}
            title="Selecionar tamanho da tela do dispositivo"
          >
            {Object.entries(VIEWPORT_SIZES).map(([key, item]) => (
              <option key={key} value={key}>
                {item.icon} {item.label}
              </option>
            ))}
          </select>
          {VIEWPORT_SIZES[viewportMode].height && (
            <button
              type="button"
              className={`editor-browser-btn ${isLandscape ? "active" : ""}`}
              onClick={() => setIsLandscape(!isLandscape)}
              title={isLandscape ? "Girar para Retrato" : "Girar para Paisagem (Landscape)"}
            >
              🔄
            </button>
          )}
        </div>

        {/* 📊 Badges de Telemetria e Gaveta DevTools */}
        <div className="editor-browser-meta-group">
          {portasStr && (
            <span className="editor-browser-status-badge status-ok" title="Porta ativa no sandbox">
              🟢 {portasStr}
            </span>
          )}
          {memMb !== undefined && (
            <span className="editor-browser-duration-badge" title="Consumo de RAM do sandbox">
              {memMb}MB RAM
            </span>
          )}
          <button
            type="button"
            className={`editor-browser-tool-btn ${showDrawer && drawerTab === "logs" ? "active" : ""}`}
            title="Logs do servidor web em tempo real"
            onClick={() => {
              if (showDrawer && drawerTab === "logs") {
                setShowDrawer(false);
              } else {
                setDrawerTab("logs");
                setShowDrawer(true);
              }
            }}
          >
            📄 Logs
          </button>
          <button
            type="button"
            className={`editor-browser-tool-btn ${showDrawer && drawerTab === "network" ? "active" : ""}`}
            title="Requisições de rede"
            onClick={() => {
              if (showDrawer && drawerTab === "network") {
                setShowDrawer(false);
              } else {
                setDrawerTab("network");
                setShowDrawer(true);
              }
            }}
          >
            🌐 Rede
          </button>
          <button
            type="button"
            className={`editor-browser-tool-btn ${showDrawer && drawerTab === "inspector" ? "active" : ""}`}
            title="Inspecionar DOM"
            onClick={() => {
              if (showDrawer && drawerTab === "inspector") {
                setShowDrawer(false);
              } else {
                setDrawerTab("inspector");
                setShowDrawer(true);
              }
            }}
          >
            🔍 DOM
          </button>
          <button
            type="button"
            className={`editor-browser-tool-btn ${showDrawer && drawerTab === "replay" ? "active" : ""}`}
            title="Replay da sessão (vídeo + trace)"
            onClick={() => {
              if (showDrawer && drawerTab === "replay") {
                setShowDrawer(false);
              } else {
                setDrawerTab("replay");
                setShowDrawer(true);
              }
            }}
          >
            🎬 Replay
          </button>
          {image && renderMode === "headless" && (
            <button
              type="button"
              className="editor-browser-tool-btn"
              title="Baixar screenshot"
              onClick={downloadScreenshot}
            >
              📸
            </button>
          )}
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

      {/* ⭐ Barra de Favoritos Rápidos (Dev Bookmarks) */}
      <div className="browser-bookmarks-bar">
        <span className="browser-bookmarks-title">Atalhos:</span>
        {DEV_BOOKMARKS.map((bm) => (
          <button
            key={bm.url}
            type="button"
            className={`browser-bookmark-btn ${currentUrl === bm.url ? "active" : ""}`}
            onClick={() => void navegar(bm.url)}
          >
            {bm.label}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 11, opacity: 0.7 }}>Zoom:</span>
          <button
            type="button"
            className="browser-zoom-btn"
            onClick={() => setZoomLevel((z) => Math.max(50, z - 10))}
          >
            -
          </button>
          <span style={{ fontSize: 11, minWidth: 35, textAlign: "center" }}>{zoomLevel}%</span>
          <button
            type="button"
            className="browser-zoom-btn"
            onClick={() => setZoomLevel((z) => Math.min(150, z + 10))}
          >
            +
          </button>
        </div>
      </div>

      {erro && (
        <div className="editor-browser-error-banner">
          <span>⚠️ {erro}</span>
        </div>
      )}

      {(consoleErrors.length > 0 || pageErrors.length > 0) && (
        <div className="tool-card-error-banner" style={{ margin: "8px 14px" }}>
          <div className="tool-card-error-banner-title">⚠️ Erros no Console/Página:</div>
          {pageErrors.map((err, i) => (
            <div key={`p-${i}`} className="tool-card-error-banner-page">
              [PAGE ERROR] {err}
            </div>
          ))}
          {consoleErrors.map((err, i) => (
            <div key={`c-${i}`}>{err}</div>
          ))}
        </div>
      )}

      {/* 🖥️ Viewport Principal com Moldura de Dispositivo */}
      <div className="editor-browser-viewport-wrapper">
        <div className="editor-browser-viewport-scroller">
          <div
            className={`editor-browser-device-frame ${viewportMode !== "responsive" ? "device-frame-active" : ""}`}
            style={{
              width: viewportWidth,
              height: viewportHeight,
              transform: zoomLevel !== 100 ? `scale(${zoomLevel / 100})` : undefined,
              transformOrigin: "top center",
            }}
          >
            {renderMode === "live" ? (
              <iframe
                ref={iframeRef}
                src={currentUrl || initialUrl}
                className="browser-live-iframe"
                title={title || "Live Browser Preview"}
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              />
            ) : streamActive ? (
              <div className="editor-browser-screen-frame">
                <canvas
                  ref={canvasRef}
                  className="editor-browser-screen-img browser-stream-canvas"
                  onClick={clicarNoStream}
                  title="Ao vivo — clique em qualquer elemento para interagir"
                />
                {clickIndicator && (
                  <div
                    className="editor-browser-click-ripple"
                    style={{ left: clickIndicator.x, top: clickIndicator.y }}
                  />
                )}
              </div>
            ) : image ? (
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
                <h3>Navegador Headless / Lightpanda</h3>
                <p>Digite uma URL acima ou clique em um dos atalhos rápidos.</p>
                <button
                  type="button"
                  className="theme-btn primary"
                  onClick={() => void navegar(urlInput || initialUrl)}
                >
                  Abrir {urlInput || initialUrl}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 📑 Gaveta Lateral de Inspeção & DevTools */}
        {showDrawer && (
          <div className="editor-browser-inspector-drawer">
            <div className="editor-browser-inspector-header">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button
                  type="button"
                  className={`editor-browser-tool-btn ${drawerTab === "logs" ? "active" : ""}`}
                  onClick={() => setDrawerTab("logs")}
                >
                  Logs do Servidor
                </button>
                <button
                  type="button"
                  className={`editor-browser-tool-btn ${drawerTab === "network" ? "active" : ""}`}
                  onClick={() => setDrawerTab("network")}
                >
                  Rede ({networkLog.length})
                </button>
                <button
                  type="button"
                  className={`editor-browser-tool-btn ${drawerTab === "inspector" ? "active" : ""}`}
                  onClick={() => setDrawerTab("inspector")}
                >
                  DOM & Digitação
                </button>
                <button
                  type="button"
                  className={`editor-browser-tool-btn ${drawerTab === "replay" ? "active" : ""}`}
                  onClick={() => setDrawerTab("replay")}
                >
                  Replay{replayData ? ` (${replayData.actions.length})` : ""}
                </button>
              </div>
              <button
                type="button"
                className="editor-browser-btn"
                onClick={() => setShowDrawer(false)}
                title="Fechar Gaveta"
              >
                ×
              </button>
            </div>

            <div className="editor-browser-inspector-body">
              {drawerTab === "logs" && (
                <div className="browser-logs-panel">
                  <div className="browser-logs-toolbar">
                    <span className="text-xs text-muted">
                      Streaming de stdout/stderr da porta do sandbox
                    </span>
                    <button
                      type="button"
                      className="browser-logs-clear-btn"
                      onClick={() => setServerLogs("")}
                    >
                      Limpar
                    </button>
                  </div>
                  <pre className="browser-logs-content">
                    {serverLogs || "Nenhum log capturado ainda. O servidor pode estar ocioso."}
                  </pre>
                </div>
              )}

              {drawerTab === "network" && (
                <div className="browser-network-panel">
                  {networkLog.length === 0 ? (
                    <p className="text-xs text-muted" style={{ padding: 12 }}>
                      Nenhuma requisição interceptada ainda.
                    </p>
                  ) : (
                    <table className="browser-network-table">
                      <thead>
                        <tr>
                          <th>Método</th>
                          <th>Status</th>
                          <th>URL</th>
                          <th>Tipo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {networkLog.map((req, idx) => (
                          <tr key={idx}>
                            <td>
                              <span className={`method-badge method-${req.method.toLowerCase()}`}>
                                {req.method}
                              </span>
                            </td>
                            <td>
                              <span
                                className={`status-badge ${req.status && req.status < 400 ? "status-ok" : "status-err"}`}
                              >
                                {req.status ?? "—"}
                              </span>
                            </td>
                            <td className="network-url-cell" title={req.url}>
                              {req.url}
                            </td>
                            <td>{req.resource_type || "xhr"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {drawerTab === "inspector" && (
                <div className="browser-inspector-form">
                  <div className="form-group">
                    <label style={{ fontSize: 12 }}>Seletor CSS para digitação:</label>
                    <input
                      type="text"
                      className="input-text"
                      placeholder="input[name='email'] ou #submit-btn"
                      value={selectorInput}
                      onChange={(e) => setSelectorInput(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label style={{ fontSize: 12 }}>Texto a preencher:</label>
                    <input
                      type="text"
                      className="input-text"
                      placeholder="meu-email@sicoob.com.br"
                      value={textInput}
                      onChange={(e) => setTextInput(e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn-primary"
                    style={{ width: "100%", marginBottom: 12 }}
                    onClick={() => void enviarTexto()}
                    disabled={loading || !selectorInput.trim()}
                  >
                    Digitar no Campo
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    style={{ width: "100%", marginBottom: 12 }}
                    onClick={() => void verConteudo()}
                  >
                    Extrair Texto Visível do DOM
                  </button>
                  {content && (
                    <pre className="browser-content-preview">
                      {content}
                    </pre>
                  )}
                </div>
              )}

              {drawerTab === "replay" && (
                <BrowserReplayPanel loading={replayLoading} error={replayError} data={replayData} />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Botão flutuante para sair de tela cheia se necessário */}
      {isFullscreen && (
        <button
          type="button"
          className="browser-floating-exit-fullscreen"
          onClick={() => void toggleFullscreen()}
          title="Sair da Tela Cheia (Esc / F11)"
        >
          🗗 Sair da Tela Cheia
        </button>
      )}
    </div>
  );
}
