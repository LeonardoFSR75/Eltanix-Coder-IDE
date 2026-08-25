import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  EditorBrowserView,
  initialResultState,
  resultReducer,
  type BrowserResultState,
} from "./EditorBrowserView";

vi.mock("@/lib/ide-store", () => ({
  useIde: () => ({ activeSessionId: "test-session" }),
}));

// Nenhuma destas deveria ser chamada nos testes abaixo (modo Live com um
// hostname bloqueado pela heurística client-side retorna antes de qualquer
// chamada de rede) — mockadas mesmo assim para o teste nunca depender de
// `fetch`/rede de verdade em jsdom.
vi.mock("@/lib/api/browser", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/browser")>("@/lib/api/browser");
  return {
    ...actual,
    browserAction: vi.fn(),
    closeBrowserSession: vi.fn(),
    getBrowserReplay: vi.fn(),
    getBrowserNetworkLog: vi.fn(),
    getBrowserStreamTicket: vi.fn(),
  };
});

vi.mock("@/lib/api/sandbox", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/sandbox")>("@/lib/api/sandbox");
  return { ...actual, getSandboxStats: vi.fn(), getSandboxServerLogs: vi.fn() };
});

// ── Reducer (item 12) — regressão do bug real: `reiniciar()` esquecia campos ──
//
// Antes do reducer único, `reiniciar()` zerava 9 dos ~18 campos manualmente e
// esquecia o resto (`durationMs`/`engineUsed`/`serverLogs`/`sandboxStats`/
// `currentUrl`/`urlInput`), deixando badges obsoletas na tela depois de
// "Reiniciar". Este teste prova que a action `reset` fecha essa classe de bug
// estruturalmente: preenche TODO campo com um valor não-default via `patch`,
// despacha `reset`, e compara com um estado inicial fresco — se um único
// campo escapasse do reset, a comparação profunda abaixo falharia.
describe("resultReducer", () => {
  it("patch faz merge parcial, preservando os campos não tocados", () => {
    const estado = initialResultState("http://localhost:5400");
    const proximo = resultReducer(estado, { type: "patch", payload: { loading: true } });

    expect(proximo.loading).toBe(true);
    expect(proximo.urlInput).toBe("http://localhost:5400");
    expect(proximo).not.toBe(estado);
  });

  it("reset limpa TODO campo, mesmo depois de uma sequência de patches preenchendo tudo", () => {
    const urlInicial = "http://localhost:5400";
    const estadoInicial = initialResultState(urlInicial);

    const tudoPreenchido: BrowserResultState = {
      urlInput: "http://web:5400/admin",
      currentUrl: "http://eltanix-abc123:5400",
      title: "Página de teste",
      status: 200,
      durationMs: 842,
      engineUsed: "chromium",
      image: "base64-fake-image",
      content: "<html>...</html>",
      loading: true,
      erro: "algum erro anterior",
      consoleErrors: ["erro 1"],
      pageErrors: ["erro de página"],
      originalUrl: "http://web:5400/admin",
      urlIsInternalFallback: true,
      internalHostnameWarning: "aviso qualquer",
      iframeLoadFailed: true,
      serverLogs: "log de servidor acumulado",
      networkLog: [
        { method: "GET", url: "http://web:5400/api", status: 200, duration_ms: 12, size_bytes: 512 },
      ],
      streamFrameReady: true,
    };
    // Confere que a fixture acima cobre de fato TODO campo da interface —
    // se um campo novo for adicionado a `BrowserResultState` sem entrar
    // aqui, este teste passaria "por acidente" sem testar o campo novo.
    expect(Object.keys(tudoPreenchido).sort()).toEqual(Object.keys(estadoInicial).sort());

    const depoisDoReset = resultReducer(
      { ...estadoInicial, ...tudoPreenchido },
      { type: "reset", url: urlInicial },
    );

    expect(depoisDoReset).toEqual(initialResultState(urlInicial));
  });

  it("reset usa a URL nova passada na action, não a antiga", () => {
    const preenchido = resultReducer(initialResultState("http://a"), {
      type: "patch",
      payload: { currentUrl: "http://a/pagina-2", loading: true },
    });

    const depoisDoReset = resultReducer(preenchido, { type: "reset", url: "http://b" });

    expect(depoisDoReset).toEqual(initialResultState("http://b"));
    expect(depoisDoReset.currentUrl).toBe("http://b");
  });
});

// ── Banner de aviso (itens 2/5) ──────────────────────────────────────────
describe("EditorBrowserView — aviso de hostname Docker-interno em modo Live", () => {
  it("bloqueia a navegação e mostra o aviso quando o host só existe na rede Docker", async () => {
    const user = userEvent.setup();
    render(<EditorBrowserView initialUrl="http://localhost:5400" sessionId="s1" />);

    const input = screen.getByLabelText("Endereço da página");
    await user.clear(input);
    await user.type(input, "http://web:5400/admin");
    await user.click(screen.getByRole("button", { name: "Ir" }));

    const aviso = await screen.findByRole("alert");
    expect(aviso.textContent).toContain("web");
    expect(aviso.textContent).toContain("Docker");

    // O iframe nunca chega a apontar pro host bloqueado.
    const iframe = document.querySelector("iframe.browser-live-iframe") as HTMLIFrameElement | null;
    expect(iframe?.src ?? "").not.toContain("web:5400");
  });

  it("não mostra aviso nenhum para um host público comum", async () => {
    const user = userEvent.setup();
    render(<EditorBrowserView initialUrl="http://localhost:5400" sessionId="s1" />);

    const input = screen.getByLabelText("Endereço da página");
    await user.clear(input);
    await user.type(input, "http://localhost:5400");
    await user.click(screen.getByRole("button", { name: "Ir" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
