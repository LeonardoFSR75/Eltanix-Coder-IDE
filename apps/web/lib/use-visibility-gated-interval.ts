"use client";

import { useEffect, useRef } from "react";

/**
 * `setInterval` que pausa quando a aba não está visível
 * (`document.visibilityState !== "visible"`) e dispara uma busca extra ao
 * voltar o foco — extraído da flag `ativo` que cada poller de
 * `EditorBrowserView.tsx` reimplementava manualmente (item 14 do plano de
 * robustez do navegador interno).
 *
 * `callback` recebe `aindaValido()`, equivalente ao antigo `let ativo = true`
 * de cada efeito: falso depois que o hook desmonta ou `enabled`/`intervalMs`
 * mudam, para o chamador evitar aplicar um resultado tardio de uma
 * requisição já obsoleta.
 */
export function useVisibilityGatedInterval(
  callback: (aindaValido: () => boolean) => void | Promise<void>,
  intervalMs: number,
  enabled = true,
): void {
  const callbackRef = useRef(callback);
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return undefined;
    let valido = true;
    const aindaValido = () => valido;

    const tick = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void callbackRef.current(aindaValido);
    };

    tick();
    const timer = setInterval(tick, intervalMs);

    const aoMudarVisibilidade = () => {
      if (document.visibilityState === "visible") tick();
    };
    document.addEventListener("visibilitychange", aoMudarVisibilidade);

    return () => {
      valido = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", aoMudarVisibilidade);
    };
  }, [enabled, intervalMs]);
}
