"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
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
import { getSandboxServerLogs } from "@/lib/api/sandbox";
import { HttpError } from "@/lib/client";
import { useIde } from "@/lib/ide-store";
import { useSandboxStats } from "@/lib/use-sandbox-stats";
import { useVisibilityGatedInterval } from "@/lib/use-visibility-gated-interval";

import { BrowserReplayPanel } from "./BrowserReplayPanel";
import { PanelState } from "./PanelState";

export type ViewportMode = "responsive" | "desktop" | "laptop" | "tablet" | "mobile" | "mobile-max";
export type RenderMode = "live" | "headless";
export type BrowserEngine = "auto" | "lightpanda" | "chromium";

interface BrowserTab {
  id: string;
  title: string;
  url: string;
  mode: RenderMode;
  // Per aba, não global — item 12 do plano de robustez do navegador interno:
  // antes era um único `useState` compartilhado por todas as abas, então
  // trocar de aba "esquecia" o motor escolhido para a aba anterior.
  engine: BrowserEngine;
  history: string[];
  historyIndex: number;
}

interface EditorBrowserViewProps {
  initialUrl?: string;
  sessionId?: string;
  isStandalone?: boolean;
  /** Força o modo inicial da primeira aba — usado quando quem abriu já sabe
   * que a URL só é alcançável via o serviço de navegador (ex.: porta de um
   * sandbox, resolvida por `sicoobito-<sessionId>:<porta>` dentro do
   * `browser_net`), nunca por um iframe direto no navegador real. */
  initialMode?: RenderMode;
}

const VIEWPORT_SIZES: Record<ViewportMode, { width: string; height?: string; label: string; icon: string }> = {
  responsive: { width: "100%", label: "Responsivo (100%)", icon: "🖥️" },
  desktop: { width: "1280px", label: "Desktop (1280px)", icon: "💻" },
  laptop: { width: "1024px", label: "Laptop (1024px)", icon: "💻" },
  tablet: { width: "768px", height: "1024px", label: "Tablet (768x1024)", icon: "📟" },
  mobile: { width: "375px", height: "667px", label: "Mobile SE (375x667)", icon: "📱" },
  "mobile-max": { width: "390px", height: "844px", label: "Mobile Max (390x844)", icon: "📲" },
};

// Hostnames que só existem dentro da rede Docker do projeto (`browser_net`)
// — nunca são alcançáveis pelo navegador REAL do usuário, que roda fora do
// Docker. Checagem client-side best-effort: complementa (não substitui) o
// sinal `url_is_internal_fallback` que o backend manda quando ELE faz essa
// substituição por baixo dos panos (ver `services/browser/app.py::validate_url`
// e o addendum do ADR 0007) — este regex cobre o caso de o usuário digitar
// um desses hosts diretamente na barra de endereço do modo Live.
const DOCKER_INTERNAL_HOSTNAME_RE =
  /^(sicoobito-[\w-]+|web|api|executor|redis|minio|postgres|browser|ollama|mcp-scanner|host\.docker\.internal)$/i;

function suspectedDockerInternalHostname(url: string): string | null {
  try {
    const hostname = new URL(url).hostname;
    return DOCKER_INTERNAL_HOSTNAME_RE.test(hostname) ? hostname : null;
  } catch {
    return null;
  }
}

// Schema real de portas publicadas no host — ver o cabeçalho de
// `docker-compose.yml` (faixa 5400-5499). `:5406 browser` fica de fora de
// propósito: aquela rede é `internal: true` e nunca publica porta no host
// (ver `services/browser/app.py` e o addendum do ADR 0007) — um bookmark
// pra lá reproduziria a classe de bug que este arquivo existe pra evitar.
// Teto de tentativas de reconexão automática do streaming CDP antes de
// desistir e pedir intervenção manual (item 13c do plano de robustez do
// navegador interno) — sem teto, uma sessão de navegador morta de verdade
// reconectaria para sempre, pedindo um ticket novo a cada tentativa.
const MAX_STREAM_RECONNECT_ATTEMPTS = 5;

const DEV_BOOKMARKS = [
  { label: ":5400 Web", url: "http://localhost:5400" },
  { label: ":5401 API/Swagger", url: "http://localhost:5401/docs" },
  { label: ":5408 MinIO Console", url: "http://localhost:5408" },
  { label: ":5410 MCP Scanner", url: "http://localhost:5410" },
];

// ── Estado consolidado do "resultado" da sessão de navegador ───────────────
// Item 12 do plano de robustez do navegador interno: antes eram ~18 `useState`
// independentes cobrindo URL/título/status/imagem/erros/logs/stats — e
// `reiniciar()` resetava só uma parte deles manualmente, esquecendo
// `durationMs`/`engineUsed`/`serverLogs`/`sandboxStats`/`currentUrl`/
// `urlInput` (badges e endereço ficavam obsoletos depois de "Reiniciar", um
// bug real). Um reducer único com uma action `reset` central torna essa
// omissão estruturalmente impossível: resetar volta ao estado inicial
// inteiro, não exige lembrar de zerar cada campo um por um. A action `patch`
// (merge parcial, no espírito do `setState` de objeto) evita o boilerplate
// de uma dúzia de `case` nomeados para cada transição — a maioria dos
// call-sites só precisa atualizar 1-3 campos relacionados de uma vez.
export interface BrowserResultState {
  urlInput: string;
  currentUrl: string | null;
  title: string | null;
  status: number | null;
  durationMs: number | null;
  engineUsed: string | null;
  image: string | null;
  content: string | null;
  loading: boolean;
  erro: string | null;
  consoleErrors: string[];
  pageErrors: string[];
  /** URL original pedida pelo usuário quando o backend sinaliza
   * `url_is_internal_fallback` — usada no link "abrir em nova janela" (que
   * roda no navegador real, não dentro do serviço de navegador). */
  originalUrl: string | null;
  urlIsInternalFallback: boolean;
  /** Aviso do modo Live: hostname Docker-interno detectado antes de navegar
   * (heurística client-side) — bloqueia o `src` do iframe em vez de deixar
   * a tela em branco silenciosa. */
  internalHostnameWarning: string | null;
  iframeLoadFailed: boolean;
  serverLogs: string;
  networkLog: NetworkLogEntry[];
  /** `true` assim que o streaming CDP (canvas) desenhou seu primeiro frame de
   * verdade — item 13 do plano de robustez do navegador interno. Enquanto
   * falso, o último `image` (screenshot estático) continua visível por cima
   * do canvas, fechando o "flash" de tela vazia entre iniciar o stream e o
   * primeiro frame chegar. Não confundir com `image`: os frames do stream em
   * si NUNCA passam por aqui — iriam a um re-render por frame (10-30fps),
   * anulando a otimização de desenhar direto no canvas via ref. Só esta
   * transição única (false → true) por sessão de stream passa pelo reducer. */
  streamFrameReady: boolean;
}

export type BrowserResultAction =
  | { type: "patch"; payload: Partial<BrowserResultState> }
  | { type: "reset"; url: string };

// Exportados só para o teste de regressão do item 12/19 (garantir que
// `reset` de fato limpa todo campo, o bug que motivou este reducer existir)
// — nenhum outro módulo fora deste arquivo e do teste deveria importá-los.
export function initialResultState(url: string): BrowserResultState {
  return {
    urlInput: url,
    currentUrl: url,
    title: null,
    status: null,
    durationMs: null,
    engineUsed: null,
    image: null,
    content: null,
    loading: false,
    erro: null,
    consoleErrors: [],
    pageErrors: [],
    originalUrl: null,
    urlIsInternalFallback: false,
    internalHostnameWarning: null,
    iframeLoadFailed: false,
    serverLogs: "",
    networkLog: [],
    streamFrameReady: false,
  };
}

export function resultReducer(
  state: BrowserResultState,
  action: BrowserResultAction,
): BrowserResultState {
  switch (action.type) {
    case "patch":
      return { ...state, ...action.payload };
    case "reset":
      return initialResultState(action.url);
    default:
      return state;
  }
}

export function EditorBrowserView({
  initialUrl = "http://localhost:5400",
  sessionId: customSessionId,
  isStandalone = false,
  initialMode = "live",
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
      mode: initialMode,
      engine: "auto",
      history: [initialUrl],
      historyIndex: 0,
    },
  ]);
  const [activeTabId, setActiveTabId] = useState<string>("tab-1");

  const currentTab = tabs.find((t) => t.id === activeTabId) || tabs[0];
  // Fonte única de verdade para modo/motor: os dois vivem só em `tabs`, por
  // aba. Antes, `renderMode` era um `useState` próprio sincronizado só por
  // um efeito (ao trocar de aba) + dois handlers manuais (ao trocar de
  // modo) — uma segunda fonte de verdade a mais para divergir da real.
  const renderMode = currentTab.mode;
  const browserEngine = currentTab.engine;

  const updateCurrentTab = useCallback(
    (changes: Partial<Pick<BrowserTab, "mode" | "engine">>) => {
      setTabs((prev) => prev.map((t) => (t.id === activeTabId ? { ...t, ...changes } : t)));
    },
    [activeTabId],
  );

  const [result, dispatch] = useReducer(resultReducer, initialUrl, initialResultState);
  // `status`/`durationMs` ficam guardados no reducer (a resposta de
  // `navigate` já os traz) mas nenhuma parte do JSX os lê hoje — mesmo
  // comportamento de antes da consolidação, não algo perdido nesta
  // refatoração; por isso não entram na desestruturação abaixo.
  const {
    urlInput,
    currentUrl,
    title,
    engineUsed,
    image,
    content,
    loading,
    erro,
    consoleErrors,
    pageErrors,
    originalUrl,
    urlIsInternalFallback,
    internalHostnameWarning,
    iframeLoadFailed,
    serverLogs,
    networkLog,
    streamFrameReady,
  } = result;

  const patch = useCallback((payload: Partial<BrowserResultState>) => {
    dispatch({ type: "patch", payload });
  }, []);

  // Poller "singleton" por sessão, compartilhado com `StatusBar` — ver
  // `lib/use-sandbox-stats.ts` (item 14 do plano de robustez do navegador
  // interno). Pausado em modo Live: o iframe faz bypass do backend, então os
  // stats do sandbox ficam irrelevantes para o que está na tela.
  const sandboxStats = useSandboxStats(sessionId || activeSessionId, {
    enabled: renderMode !== "live",
  });

  const [clickIndicator, setClickIndicator] = useState<{ x: number; y: number } | null>(null);

  // Responsividade & Fullscreen
  const [viewportMode, setViewportMode] = useState<ViewportMode>("responsive");
  const [isLandscape, setIsLandscape] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [zoomLevel, setZoomLevel] = useState<number>(100);

  // DevTools & Drawer
  const [showDrawer, setShowDrawer] = useState(false);
  const [drawerTab, setDrawerTab] = useState<"inspector" | "logs" | "network" | "replay">("logs");
  const [replayData, setReplayData] = useState<ReplayDetail | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [replayRefreshKey, setReplayRefreshKey] = useState(0);
  const [selectorInput, setSelectorInput] = useState("");
  const [textInput, setTextInput] = useState("");

  // Streaming ao vivo (CDP screencast) no modo Agente
  const [streamActive, setStreamActive] = useState(false);
  const [streamConnecting, setStreamConnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const streamFrameImgRef = useRef<HTMLImageElement>(new Image());
  // `true` só após o primeiro `drawImage` de verdade nesta conexão — usado
  // pra disparar `streamFrameReady` no reducer uma única vez por stream, não
  // a cada frame (ver comentário do campo em `BrowserResultState`).
  const streamFirstFrameRef = useRef(false);
  // `pararStream()` marca aqui ANTES de fechar o socket, para o `onclose`
  // saber que foi um encerramento deliberado (usuário/troca de modo) e não
  // tentar reconectar — item 13c do plano de robustez do navegador interno.
  const streamDeliberateStopRef = useRef(false);
  const streamReconnectAttemptsRef = useRef(0);
  const streamReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Sincroniza estado da URL quando a aba ativa muda
  useEffect(() => {
    if (currentTab) {
      patch({ urlInput: currentTab.url, currentUrl: currentTab.url, title: currentTab.title });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    patch({ loading: true, erro: null });
    try {
      const shot = await browserAction({ sessionId, action: "screenshot", engine: browserEngine });
      const payload: Partial<BrowserResultState> = {
        consoleErrors: shot.console_errors ?? [],
        pageErrors: shot.page_errors ?? [],
      };
      if (shot.image_base64) payload.image = shot.image_base64;
      if (shot.url) payload.currentUrl = shot.url;
      if (shot.title) payload.title = shot.title;
      if (shot.engine_used) payload.engineUsed = shot.engine_used;
      patch(payload);
    } catch (err) {
      patch({ erro: err instanceof Error ? err.message : String(err) });
    } finally {
      patch({ loading: false });
    }
  }, [sessionId, renderMode, browserEngine, patch]);

  // Streaming ao vivo — só faz sentido no modo Agente (headless/CDP); no modo
  // Live o iframe já é a própria fonte visual, sem precisar de screencast.
  const clearStreamReconnectTimer = useCallback(() => {
    if (streamReconnectTimerRef.current) {
      clearTimeout(streamReconnectTimerRef.current);
      streamReconnectTimerRef.current = null;
    }
  }, []);

  const pararStream = useCallback(() => {
    streamDeliberateStopRef.current = true;
    clearStreamReconnectTimer();
    streamReconnectAttemptsRef.current = 0;
    wsRef.current?.close();
    wsRef.current = null;
    setStreamActive(false);
    setStreamConnecting(false);
    streamFirstFrameRef.current = false;
    patch({ streamFrameReady: false });
  }, [clearStreamReconnectTimer, patch]);

  const iniciarStream = useCallback(async () => {
    if (renderMode !== "headless" || wsRef.current) return;
    streamDeliberateStopRef.current = false;
    streamFirstFrameRef.current = false;
    setStreamConnecting(true);
    patch({ erro: null, streamFrameReady: false });
    try {
      const { ticket } = await getBrowserStreamTicket(sessionId);
      const url = buildBrowserStreamUrl(sessionId, ticket);
      const socket = new WebSocket(url);
      wsRef.current = socket;

      socket.onopen = () => {
        streamReconnectAttemptsRef.current = 0;
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
            // Só a PRIMEIRA vez — as demais são puramente imperativas (ref),
            // sem passar pelo reducer/re-render (ver comentário do campo
            // `streamFrameReady` em `BrowserResultState`).
            if (!streamFirstFrameRef.current) {
              streamFirstFrameRef.current = true;
              patch({ streamFrameReady: true });
            }
          };
          img.src = `data:image/jpeg;base64,${msg.data}`;
        } catch {
          // Frame malformado — ignora, o próximo chega em instantes.
        }
      };

      socket.onerror = () => {
        patch({ erro: "falha na conexão de streaming ao vivo" });
      };

      socket.onclose = () => {
        wsRef.current = null;
        setStreamActive(false);
        setStreamConnecting(false);
        // Encerramento deliberado (usuário pausou, saiu do modo Agente,
        // desmontou) — `pararStream()`/o efeito de desmontagem já marcaram
        // isto antes de fechar o socket. Não reconectar nesse caso.
        if (streamDeliberateStopRef.current) return;
        if (streamReconnectAttemptsRef.current >= MAX_STREAM_RECONNECT_ATTEMPTS) {
          patch({
            erro: "streaming ao vivo caiu e não reconectou — tente “▶ Ao Vivo” manualmente.",
          });
          return;
        }
        // Backoff exponencial (1s, 2s, 4s, 8s, teto de 10s) — pede um ticket
        // NOVO a cada tentativa (tickets são de uso único, ver `TicketStore`/
        // invariante #9 do plano); item 13c do plano de robustez do
        // navegador interno.
        const tentativa = streamReconnectAttemptsRef.current;
        streamReconnectAttemptsRef.current += 1;
        const atrasoMs = Math.min(1000 * 2 ** tentativa, 10_000);
        clearStreamReconnectTimer();
        streamReconnectTimerRef.current = setTimeout(() => {
          void iniciarStream();
        }, atrasoMs);
      };
    } catch (err) {
      setStreamConnecting(false);
      patch({ erro: err instanceof Error ? err.message : String(err) });
    }
  }, [sessionId, renderMode, patch, clearStreamReconnectTimer]);

  // Encerra o stream ao sair do modo Agente/trocar de sessão, e auto-inicia
  // ao entrar — antes exigia um segundo clique manual em "▶ Ao Vivo" depois
  // de trocar para 🤖 Agente, e a maioria dos usuários ficava no caminho de
  // poll-por-ação (screenshot sob pedido), mais lento (item 13b do plano).
  useEffect(() => {
    if (renderMode !== "headless") {
      if (wsRef.current) pararStream();
      return;
    }
    if (!streamActive && !streamConnecting) {
      void iniciarStream();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderMode, streamActive, streamConnecting]);

  useEffect(() => {
    return () => {
      streamDeliberateStopRef.current = true;
      clearStreamReconnectTimer();
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [sessionId, clearStreamReconnectTimer]);

  // Navegar para nova URL
  const navegar = useCallback(
    async (destino: string, pushHistory = true) => {
      const bruto = destino.trim();
      if (!bruto) return;
      const alvo = /^https?:\/\//i.test(bruto) ? bruto : `http://${bruto}`;

      // Checagem ANTES de qualquer mudança de estado: em modo Live, se o
      // host parece Docker-interno, a navegação nem chega a atualizar
      // `currentUrl`/a aba — senão o `src` reativo do iframe (JSX abaixo)
      // apontaria pra lá de qualquer jeito, mesmo pulando a atribuição
      // imperativa de `iframeRef.current.src`.
      if (renderMode === "live") {
        const hostnameSuspeito = suspectedDockerInternalHostname(alvo);
        if (hostnameSuspeito) {
          patch({
            internalHostnameWarning:
              `O host "${hostnameSuspeito}" só existe dentro da rede Docker do projeto e não é ` +
              "alcançável por este navegador — troque para o modo 🤖 Agente ou use " +
              "localhost:<porta>.",
            urlInput: alvo,
          });
          return;
        }
        patch({ internalHostnameWarning: null });
      }

      patch({ loading: true, erro: null, content: null });

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

      patch({
        currentUrl: alvo,
        urlInput: alvo,
        originalUrl: alvo,
        urlIsInternalFallback: false,
        iframeLoadFailed: false,
      });

      if (renderMode === "live") {
        if (iframeRef.current) {
          iframeRef.current.src = alvo;
        }
        patch({ loading: false });
        return;
      }

      try {
        const resultado = await browserAction({ sessionId, action: "navigate", url: alvo, engine: browserEngine });
        const finalUrl = resultado.url ?? alvo;
        const payload: Partial<BrowserResultState> = {
          currentUrl: finalUrl,
          urlInput: finalUrl,
          originalUrl: resultado.original_url ?? alvo,
          urlIsInternalFallback: Boolean(resultado.url_is_internal_fallback),
          title: resultado.title ?? null,
          status: resultado.status ?? 200,
          durationMs: resultado.duration_ms ?? null,
          consoleErrors: resultado.console_errors ?? [],
          pageErrors: resultado.page_errors ?? [],
        };
        if (resultado.engine_used) payload.engineUsed = resultado.engine_used;
        if (resultado.image_base64) payload.image = resultado.image_base64;
        patch(payload);
        if (!resultado.image_base64) {
          await capturar();
        }
      } catch (err) {
        patch({ erro: err instanceof Error ? err.message : String(err) });
      } finally {
        patch({ loading: false });
      }
    },
    [sessionId, capturar, renderMode, activeTabId, browserEngine, patch],
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
      url: "http://localhost:5400",
      mode: "live",
      engine: "auto",
      history: ["http://localhost:5400"],
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

  // Polling de logs do servidor quando o drawer de logs estiver aberto —
  // `useVisibilityGatedInterval` (item 14) substitui a flag `ativo` que este
  // efeito reimplementava manualmente, e pausa sozinho quando a aba do
  // navegador perde foco.
  const targetSid = sessionId || activeSessionId;
  useVisibilityGatedInterval(
    async (aindaValido) => {
      if (!targetSid) return;
      try {
        const data = await getSandboxServerLogs(targetSid, 200);
        if (aindaValido() && data?.logs) {
          patch({ serverLogs: data.logs });
        }
      } catch {
        // Ignora erros
      }
    },
    2500,
    showDrawer && drawerTab === "logs" && Boolean(targetSid),
  );

  // Polling do log de rede quando o drawer estiver na aba "Rede"
  useVisibilityGatedInterval(
    async (aindaValido) => {
      try {
        const data = await getBrowserNetworkLog(sessionId);
        if (aindaValido()) patch({ networkLog: data.requests ?? [] });
      } catch {
        // Ignora erros
      }
    },
    2000,
    showDrawer && drawerTab === "network",
  );

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

      patch({ loading: true, erro: null });
      try {
        const res = await browserAction({ sessionId, action: "click", x, y, engine: browserEngine });
        if (res.engine_used) patch({ engineUsed: res.engine_used });
        await new Promise((r) => setTimeout(r, 300));
        await capturar();
      } catch (err) {
        patch({ erro: err instanceof Error ? err.message : String(err) });
      } finally {
        patch({ loading: false });
      }
    },
    [sessionId, loading, capturar, browserEngine, patch],
  );

  // Mesma ideia, mas para o modo de streaming ao vivo: o próximo frame do
  // screencast já mostra o resultado, então não precisa forçar `capturar()`
  // nem o `setTimeout` de 300ms de `clicarNaCaptura` acima — verificado como
  // parte do item 13d do plano de robustez do navegador interno (este é o
  // único handler de clique alcançável enquanto `streamActive` é true).
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

      void browserAction({ sessionId, action: "click", x, y, engine: browserEngine }).catch((err) => {
        patch({ erro: err instanceof Error ? err.message : String(err) });
      });
    },
    [sessionId, browserEngine, patch],
  );

  const enviarTexto = useCallback(async () => {
    if (!selectorInput.trim() || !textInput) return;
    patch({ loading: true, erro: null });
    try {
      const res = await browserAction({
        sessionId,
        action: "type",
        selector: selectorInput.trim(),
        text: textInput,
        engine: browserEngine,
      });
      if (res.engine_used) patch({ engineUsed: res.engine_used });
      await new Promise((r) => setTimeout(r, 300));
      await capturar();
      setTextInput("");
    } catch (err) {
      patch({ erro: err instanceof Error ? err.message : String(err) });
    } finally {
      patch({ loading: false });
    }
  }, [sessionId, selectorInput, textInput, capturar, browserEngine, patch]);

  const verConteudo = useCallback(async () => {
    patch({ erro: null });
    try {
      const resultado = await browserAction({ sessionId, action: "content", engine: browserEngine });
      if (resultado.engine_used) patch({ engineUsed: resultado.engine_used });
      patch({ content: resultado.text ?? "" });
      setDrawerTab("inspector");
      setShowDrawer(true);
    } catch (err) {
      patch({ erro: err instanceof Error ? err.message : String(err) });
    }
  }, [sessionId, browserEngine, patch]);

  const reiniciar = useCallback(async () => {
    pararStream();
    try {
      await closeBrowserSession(sessionId);
    } catch {
      // Ignora erro
    }
    // Reset completo num único dispatch — a versão anterior zerava campo por
    // campo manualmente e esquecia `durationMs`/`engineUsed`/`serverLogs`/
    // `sandboxStats`/`currentUrl`/`urlInput` (badges obsoletas depois de
    // "Reiniciar", ver comentário do reducer no topo do arquivo).
    dispatch({ type: "reset", url: currentTab.url });
    setReplayRefreshKey((k) => k + 1);
  }, [sessionId, pararStream, currentTab.url]);

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
        <div className="browser-tabs-list" role="tablist" aria-label="Abas do navegador">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={`browser-tab-item ${tab.id === activeTabId ? "active" : ""}`}
              role="tab"
              aria-selected={tab.id === activeTabId}
              tabIndex={tab.id === activeTabId ? 0 : -1}
              onClick={() => setActiveTabId(tab.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setActiveTabId(tab.id);
                }
              }}
            >
              <span className="browser-tab-icon" aria-hidden="true">
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
                  aria-label={`Fechar aba ${tab.title || tab.url}`}
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
            aria-label="Abrir nova aba"
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
            aria-label={isFullscreen ? "Sair da tela cheia" : "Entrar em tela cheia"}
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
            aria-label="Voltar"
            onClick={voltar}
            disabled={!canGoBack || loading}
          >
            ←
          </button>
          <button
            type="button"
            className="editor-browser-btn"
            title="Avançar (Alt + →)"
            aria-label="Avançar"
            onClick={avancar}
            disabled={!canGoForward || loading}
          >
            →
          </button>
          <button
            type="button"
            className={`editor-browser-btn ${loading ? "btn-spin" : ""}`}
            title="Recarregar página"
            aria-label="Recarregar página"
            onClick={recarregar}
            disabled={loading || !currentUrl}
          >
            🔄
          </button>
          <button
            type="button"
            className="editor-browser-btn"
            title="Ir para página inicial (Home)"
            aria-label="Ir para página inicial"
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
            aria-hidden="true"
          >
            {isSecure ? "🔒" : "🔓"}
          </span>
          <label htmlFor="editor-browser-url-input" className="sr-only">
            Endereço da página
          </label>
          <input
            id="editor-browser-url-input"
            type="text"
            className="editor-browser-url-input"
            value={urlInput}
            onChange={(e) => patch({ urlInput: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && void navegar(urlInput)}
            placeholder="http://localhost:5400"
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
              // `currentUrl` pode ser um hostname Docker-interno resolvido
              // pelo backend (`url_is_internal_fallback`) — uma nova janela
              // do sistema roda fora do Docker, então usa `originalUrl`
              // (o que o usuário pediu) nesse caso.
              href={urlIsInternalFallback ? originalUrl || currentUrl : currentUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="browser-open-external-btn"
              title="Abrir em nova janela do sistema"
              aria-label="Abrir em nova janela do sistema"
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
            onClick={() => updateCurrentTab({ mode: "live" })}
            title="Modo Live Iframe (Interação nativa, HMR e WebSockets em tempo real)"
          >
            ⚡ Live
          </button>
          <button
            type="button"
            className={`browser-mode-btn ${renderMode === "headless" ? "active" : ""}`}
            onClick={() => {
              updateCurrentTab({ mode: "headless" });
              if (currentUrl) void navegar(currentUrl);
            }}
            title="Modo Headless Agent (Playwright / Lightpanda CDP com telemetria e inspeção)"
          >
            🤖 Agente
          </button>
          {renderMode === "headless" && (
            <>
              <button
                type="button"
                className={`browser-mode-btn ${streamActive ? "active" : ""}`}
                onClick={() => (streamActive ? pararStream() : void iniciarStream())}
                disabled={streamConnecting}
                title="Streaming ao vivo via CDP screencast (em vez de screenshot sob pedido)"
              >
                {streamConnecting ? "…" : streamActive ? "⏸ Ao Vivo" : "▶ Ao Vivo"}
              </button>
              <div
                className="browser-engine-switcher"
                style={{
                  display: "inline-flex",
                  gap: "2px",
                  alignItems: "center",
                  background: "rgba(255, 255, 255, 0.05)",
                  padding: "2px 4px",
                  borderRadius: "6px",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                }}
              >
                <button
                  type="button"
                  className={`browser-mode-btn ${browserEngine === "auto" ? "active" : ""}`}
                  onClick={() => updateCurrentTab({ engine: "auto" })}
                  title="Auto: Lightpanda para DOM/scraping ultraleve (25MB RAM) e Chromium para screenshots"
                  style={{ fontSize: "11px", padding: "2px 6px" }}
                >
                  ⚡ Auto
                </button>
                <button
                  type="button"
                  className={`browser-mode-btn ${browserEngine === "lightpanda" ? "active" : ""}`}
                  onClick={() => updateCurrentTab({ engine: "lightpanda" })}
                  title="Lightpanda Browser (C/C++ ultraleve - 25MB RAM, sub-50ms cold start)"
                  style={{ fontSize: "11px", padding: "2px 6px" }}
                >
                  🐼 Lightpanda
                </button>
                <button
                  type="button"
                  className={`browser-mode-btn ${browserEngine === "chromium" ? "active" : ""}`}
                  onClick={() => updateCurrentTab({ engine: "chromium" })}
                  title="Chromium Playwright (Renderização completa, vídeos e screenshots)"
                  style={{ fontSize: "11px", padding: "2px 6px" }}
                >
                  🌐 Chromium
                </button>
              </div>
            </>
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
              aria-label={isLandscape ? "Girar para retrato" : "Girar para paisagem"}
            >
              🔄
            </button>
          )}
        </div>

        {/* 📊 Badges de Telemetria e Gaveta DevTools */}
        <div className="editor-browser-meta-group">
          {engineUsed && (
            <span
              className="editor-browser-status-badge"
              style={{
                background: engineUsed === "lightpanda" ? "rgba(16, 185, 129, 0.15)" : "rgba(59, 130, 246, 0.15)",
                color: engineUsed === "lightpanda" ? "#34d399" : "#60a5fa",
                border: "1px solid currentColor",
                fontSize: "11px",
              }}
              title={`Motor ativo: ${engineUsed === "lightpanda" ? "Lightpanda (25MB RAM / Sub-50ms)" : "Chromium (Full Render)"}`}
            >
              {engineUsed === "lightpanda" ? "🐼 Lightpanda" : "🌐 Chromium"}
            </span>
          )}
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
              aria-label="Baixar screenshot"
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
          <span style={{ fontSize: 11, opacity: 0.7 }} id="editor-browser-zoom-label">Zoom:</span>
          <button
            type="button"
            className="browser-zoom-btn"
            title="Diminuir zoom"
            aria-label="Diminuir zoom"
            onClick={() => setZoomLevel((z) => Math.max(50, z - 10))}
          >
            -
          </button>
          <span
            style={{ fontSize: 11, minWidth: 35, textAlign: "center" }}
            aria-live="polite"
            aria-labelledby="editor-browser-zoom-label"
          >
            {zoomLevel}%
          </span>
          <button
            type="button"
            className="browser-zoom-btn"
            title="Aumentar zoom"
            aria-label="Aumentar zoom"
            onClick={() => setZoomLevel((z) => Math.min(150, z + 10))}
          >
            +
          </button>
        </div>
      </div>

      {erro && (
        <div className="editor-browser-error-banner" role="alert">
          <span>⚠️ {erro}</span>
        </div>
      )}

      {internalHostnameWarning && (
        <div className="editor-browser-error-banner" role="alert">
          <span>🌐 {internalHostnameWarning}</span>
        </div>
      )}

      {iframeLoadFailed && !internalHostnameWarning && (
        <div className="editor-browser-error-banner" role="alert">
          <span>
            ⚠️ A página não carregou. Se o endereço só existe dentro do sandbox/rede Docker,
            troque para o modo 🤖 Agente.
          </span>
        </div>
      )}

      {urlIsInternalFallback && originalUrl && renderMode !== "live" && (
        <div className="editor-browser-error-banner" role="status" style={{ opacity: 0.85 }}>
          <span>
            ℹ️ Resolvido internamente via {currentUrl} (endereço Docker-interno, só visível ao
            serviço de navegador) — o link "abrir em nova janela" usa {originalUrl}.
          </span>
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
                onLoad={() => patch({ iframeLoadFailed: false })}
                // Melhor esforço: falhas de DNS/conexão dentro de um iframe
                // cross-origin normalmente não disparam `onError` (o
                // navegador mostra sua própria página de erro e ainda
                // dispara `onLoad`) — a heurística de hostname acima é a
                // defesa primária; isto cobre casos que `onError` de fato
                // reporta (ex.: bloqueio por CSP/X-Frame-Options).
                onError={() => patch({ iframeLoadFailed: true })}
              />
            ) : streamActive ? (
              <div className="editor-browser-screen-frame">
                {/* Última captura estática, sobreposta e visível até o
                    primeiro frame do screencast chegar — evita o flash de
                    "vazio" na troca one-shot → streaming (item 13a). Nunca
                    recebe clique: o canvas por cima já cobre a interação. */}
                {image && (
                  <img
                    src={`data:image/png;base64,${image}`}
                    alt=""
                    aria-hidden="true"
                    className="editor-browser-screen-img"
                    style={{
                      position: "absolute",
                      inset: 0,
                      opacity: streamFrameReady ? 0 : 1,
                      transition: "opacity 150ms ease-out",
                      pointerEvents: "none",
                    }}
                  />
                )}
                <canvas
                  ref={canvasRef}
                  className="editor-browser-screen-img browser-stream-canvas"
                  style={{
                    position: "relative",
                    opacity: streamFrameReady ? 1 : 0,
                    transition: "opacity 150ms ease-out",
                  }}
                  onClick={clicarNoStream}
                  title="Ao vivo — clique em qualquer elemento para interagir"
                  role="img"
                  aria-label={`Transmissão ao vivo de ${title || currentUrl || "página renderizada"}`}
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
                      onClick={() => patch({ serverLogs: "" })}
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
                    <PanelState kind="empty" icon="📡" message="Nenhuma requisição interceptada ainda." />
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
