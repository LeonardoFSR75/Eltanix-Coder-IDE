import { renderHook } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as sandboxApi from "@/lib/api/sandbox";
import { refreshSandboxStats, useSandboxStats } from "@/lib/use-sandbox-stats";

vi.mock("@/lib/api/sandbox", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/sandbox")>("@/lib/api/sandbox");
  return { ...actual, getSandboxStats: vi.fn() };
});

const mockedGetStats = vi.mocked(sandboxApi.getSandboxStats);

function statsFor(sessionId: string) {
  return { session_id: sessionId, status: "running", ports: [3000] };
}

// Cada teste usa um `session_id` próprio para não colidir com o cache
// module-level compartilhado entre os testes (o mesmo motivo pelo qual o
// cache é "singleton" em produção — aqui vira ruído se não isolado).
let contador = 0;
function sessionIdUnica() {
  contador += 1;
  return `sess-${contador}`;
}

describe("useSandboxStats", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockedGetStats.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("busca os stats imediatamente ao montar", async () => {
    const sid = sessionIdUnica();
    mockedGetStats.mockResolvedValue(statsFor(sid));
    const { result } = renderHook(() => useSandboxStats(sid));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current?.status).toBe("running");
    expect(mockedGetStats).toHaveBeenCalledWith(sid);
  });

  it("não busca nada quando `enabled: false`", async () => {
    const sid = sessionIdUnica();
    mockedGetStats.mockResolvedValue(statsFor(sid));
    renderHook(() => useSandboxStats(sid, { enabled: false }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mockedGetStats).not.toHaveBeenCalled();
  });

  it("compartilha UMA única chamada por ciclo entre duas instâncias montadas da mesma sessão", async () => {
    const sid = sessionIdUnica();
    mockedGetStats.mockResolvedValue(statsFor(sid));

    const a = renderHook(() => useSandboxStats(sid));
    const b = renderHook(() => useSandboxStats(sid));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(a.result.current?.status).toBe("running");
    expect(b.result.current?.status).toBe("running");
    // Ambas fazem fetch inicial no mount, mas o mesmo `session_id` reaproveita
    // a mesma `EntradaCache` — o timer do ciclo seguinte é um só.
    mockedGetStats.mockClear();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(mockedGetStats).toHaveBeenCalledTimes(1);

    a.unmount();
    b.unmount();
  });

  it("para de buscar depois que o último assinante desmonta", async () => {
    const sid = sessionIdUnica();
    mockedGetStats.mockResolvedValue(statsFor(sid));
    const { unmount } = renderHook(() => useSandboxStats(sid));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    unmount();
    mockedGetStats.mockClear();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(mockedGetStats).not.toHaveBeenCalled();
  });

  it("refreshSandboxStats força uma busca imediata e atualiza assinantes", async () => {
    const sid = sessionIdUnica();
    mockedGetStats.mockResolvedValue(statsFor(sid));
    const { result } = renderHook(() => useSandboxStats(sid));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current?.status).toBe("running");

    mockedGetStats.mockResolvedValue({ ...statsFor(sid), status: "prewarmed" });
    await act(async () => {
      await refreshSandboxStats(sid);
    });
    expect(result.current?.status).toBe("prewarmed");
  });
});
