import { renderHook } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVisibilityGatedInterval } from "@/lib/use-visibility-gated-interval";

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
}

describe("useVisibilityGatedInterval", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("chama o callback imediatamente ao montar e a cada intervalo", async () => {
    const callback = vi.fn();
    renderHook(() => useVisibilityGatedInterval(callback, 1000, true));

    expect(callback).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(callback).toHaveBeenCalledTimes(4);
  });

  it("não chama nada quando `enabled` é false", async () => {
    const callback = vi.fn();
    renderHook(() => useVisibilityGatedInterval(callback, 1000, false));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(callback).not.toHaveBeenCalled();
  });

  it("pula os ticks enquanto a aba está oculta", async () => {
    const callback = vi.fn();
    setVisibility("hidden");
    renderHook(() => useVisibilityGatedInterval(callback, 1000, true));

    expect(callback).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(callback).not.toHaveBeenCalled();
  });

  it("busca de novo assim que a aba volta a ficar visível", async () => {
    const callback = vi.fn();
    setVisibility("hidden");
    renderHook(() => useVisibilityGatedInterval(callback, 1000, true));
    expect(callback).not.toHaveBeenCalled();

    setVisibility("visible");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("passa `aindaValido` que vira falso depois de desmontar", async () => {
    let aindaValidoCapturada: (() => boolean) | undefined;
    const callback = vi.fn((aindaValido: () => boolean) => {
      aindaValidoCapturada = aindaValido;
    });
    const { unmount } = renderHook(() => useVisibilityGatedInterval(callback, 1000, true));

    expect(aindaValidoCapturada?.()).toBe(true);
    unmount();
    expect(aindaValidoCapturada?.()).toBe(false);
  });
});
