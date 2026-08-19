"use client";

import { useEffect, useState } from "react";
import { getSandboxStats, type SandboxStats } from "@/lib/api/sandbox";

const POLL_INTERVAL_MS = 4000;

interface EntradaCache {
  stats: SandboxStats | null;
  listeners: Set<(stats: SandboxStats | null) => void>;
  enabledCount: number;
  timer: ReturnType<typeof setInterval> | null;
  fetching: boolean;
}

// Cache module-level: `StatusBar` e `EditorBrowserView` pollavam
// `getSandboxStats` de forma totalmente independente, cada um a cada 4000ms,
// para a MESMA sessão — dobrando o custo do port-scan caro do executor (ver
// item 10 do plano). Um único timer por `session_id`, compartilhado entre
// quantas instâncias deste hook estiverem montadas, resolve isso na raiz
// (item 14 do plano de robustez do navegador interno).
const cache = new Map<string, EntradaCache>();

function getEntrada(sessionId: string): EntradaCache {
  let entrada = cache.get(sessionId);
  if (!entrada) {
    entrada = { stats: null, listeners: new Set(), enabledCount: 0, timer: null, fetching: false };
    cache.set(sessionId, entrada);
  }
  return entrada;
}

async function buscarECompartilhar(sessionId: string): Promise<void> {
  const entrada = getEntrada(sessionId);
  if (entrada.fetching) return;
  entrada.fetching = true;
  try {
    const stats = await getSandboxStats(sessionId);
    entrada.stats = stats ?? null;
    entrada.listeners.forEach((l) => l(entrada.stats));
  } catch {
    // Ignora — mantém o último valor conhecido, igual ao comportamento
    // anterior de cada poller isolado.
  } finally {
    entrada.fetching = false;
  }
}

function agendar(sessionId: string): void {
  const entrada = getEntrada(sessionId);
  if (entrada.timer || entrada.enabledCount <= 0) return;
  const tick = () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    void buscarECompartilhar(sessionId);
  };
  tick();
  entrada.timer = setInterval(tick, POLL_INTERVAL_MS);
}

function desagendarSeOcioso(sessionId: string): void {
  const entrada = cache.get(sessionId);
  if (!entrada || entrada.enabledCount > 0) return;
  if (entrada.timer) {
    clearInterval(entrada.timer);
    entrada.timer = null;
  }
}

/** Força uma busca imediata e devolve o resultado (usado após uma ação que muda o estado, ex.: pre-warm). */
export async function refreshSandboxStats(sessionId: string): Promise<SandboxStats | null> {
  await buscarECompartilhar(sessionId);
  return getEntrada(sessionId).stats;
}

/**
 * Stats do sandbox Docker da sessão, com polling "singleton" por
 * `session_id` (ver comentário do cache acima) e pausado quando a aba não
 * está visível. `enabled: false` (ex.: modo "⚡ Live", onde o iframe faz
 * bypass do backend e os stats ficam irrelevantes) mantém o último valor
 * conhecido sem gerar tráfego novo.
 */
export function useSandboxStats(
  sessionId: string | null | undefined,
  opts?: { enabled?: boolean },
): SandboxStats | null {
  const enabled = Boolean(sessionId) && (opts?.enabled ?? true);
  const [stats, setStats] = useState<SandboxStats | null>(() =>
    sessionId ? (cache.get(sessionId)?.stats ?? null) : null,
  );

  useEffect(() => {
    if (!sessionId) return undefined;
    const entrada = getEntrada(sessionId);
    setStats(entrada.stats);
    entrada.listeners.add(setStats);
    return () => {
      entrada.listeners.delete(setStats);
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !enabled) return undefined;
    const entrada = getEntrada(sessionId);
    entrada.enabledCount += 1;
    agendar(sessionId);
    return () => {
      entrada.enabledCount -= 1;
      desagendarSeOcioso(sessionId);
    };
  }, [sessionId, enabled]);

  useEffect(() => {
    if (!sessionId || !enabled) return undefined;
    const aoMudarVisibilidade = () => {
      if (document.visibilityState === "visible") void buscarECompartilhar(sessionId);
    };
    document.addEventListener("visibilitychange", aoMudarVisibilidade);
    return () => document.removeEventListener("visibilitychange", aoMudarVisibilidade);
  }, [sessionId, enabled]);

  return stats;
}
