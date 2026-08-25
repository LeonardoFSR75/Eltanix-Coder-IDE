"use client";

import { useCallback, useMemo, useReducer, useRef } from "react";
import { post } from "@/lib/client";
import { AgentSessionRuntime, type NotifyKind } from "./sessionRuntime";
import type { Session, SessionStatus, SessionSummary } from "./sessionTypes";

function statusOf(runtime: AgentSessionRuntime): SessionStatus {
  switch (runtime.status) {
    case "closed":
      return "closed";
    case "error":
      return "error";
    case "awaiting_approval":
      return "awaiting-approval";
    case "running":
      return "running";
    case "done":
      return "done";
    case "idle":
      return "running";
    default:
      return "running";
  }
}

/**
 * Gerencia N sessões do agente na mesma aba — o Agent Manager. Cada sessão
 * roda seu próprio `AgentSessionRuntime` (sem hook, ver sessionRuntime.ts);
 * este hook só guarda o mapa e força um re-render quando qualquer runtime
 * muda, sem re-instanciar hooks por sessão (o que violaria as regras do
 * React — a quantidade de sessões varia em tempo de execução).
 */
export function useAgentSessions({
  project,
  onFileTouched,
  onNotify,
}: {
  project: string | null;
  onFileTouched?: (path: string) => void;
  onNotify?: (kind: NotifyKind, message: string) => void;
}) {
  const runtimesRef = useRef<Map<string, AgentSessionRuntime>>(new Map());
  const activeIdRef = useRef<string | null>(null);
  // `renderTick` entra na dependência do `useMemo` abaixo de propósito: é o
  // único jeito de saber "algum runtime mudou" sem o mapa em si mudar de
  // tamanho — sem ele, o card de status ficaria congelado no primeiro valor.
  const [renderTick, bump] = useReducer((c: number) => c + 1, 0);

  const notify = useCallback(() => bump(), []);

  // Toda sessão de fundo (orquestração via spawn_agent, ADR 0004) reporta
  // cada evento SSE por este mesmo `onChange` — sem filtrar, um log/activity
  // tick de uma sessão que ninguém está olhando força o dock inteiro (com o
  // AgentPanel da sessão ATIVA) a re-renderizar. A sessão ativa sempre
  // propaga (é o que a UI mostra agora); uma sessão de fundo só re-renderiza
  // quando o resumo que a lista de abas/Agent Manager realmente exibe
  // (task/branch/status/closed) muda de verdade.
  const lastSummaryRef = useRef<Map<string, string>>(new Map());
  const notifyFor = useCallback((id: string) => {
    if (activeIdRef.current === id) {
      bump();
      return;
    }
    const runtime = runtimesRef.current.get(id);
    if (!runtime) {
      bump();
      return;
    }
    const resumo = `${runtime.task || id}|${runtime.session?.branch ?? ""}|${statusOf(runtime)}|${runtime.readOnly}`;
    if (lastSummaryRef.current.get(id) === resumo) return;
    lastSummaryRef.current.set(id, resumo);
    bump();
  }, []);

  const startSession = useCallback(
    (
      task: string,
      mode: string,
      profile?: string | null,
      focusFiles?: string[],
      focusFolder?: string | null,
      images?: string[],
    ) => {
      if (!project) return;

      const pendingId = `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      // `idBox` existe porque este runtime muda de chave no mapa (pendingId
      // → session_id de verdade) assim que o backend responde — o closure de
      // `onChange` abaixo precisa ver a chave atual, não a de quando foi
      // criado, senão `notifyFor` nunca encontra o runtime no mapa e cai no
      // fallback de sempre re-renderizar (perde a otimização pro resto da
      // vida da sessão).
      const idBox = { current: pendingId };
      const runtime = new AgentSessionRuntime({
        project,
        onFileTouched,
        onChange: () => notifyFor(idBox.current),
        onNotify,
      });
      runtime.task = task;
      runtime.append({
        kind: "user",
        text: task || (images?.length ? `[${images.length} imagem(ns) enviada(s)]` : ""),
      });

      runtimesRef.current.set(pendingId, runtime);
      activeIdRef.current = pendingId;
      notify();

      void (async () => {
        try {
          const created = await post<Session>("/api/agent/sessions", {
            task,
            mode,
            project,
            profile: profile || undefined,
            focus_files: focusFiles ?? [],
            focus_folder: focusFolder ?? undefined,
            images: images ?? [],
          });

          runtime.session = created;
          runtime.append({
            kind: "info",
            text: `sessão ${created.session_id} · branch ${created.branch || "(nenhum)"}`,
          });
          for (const aviso of created.warnings ?? []) {
            runtime.append({ kind: "error", text: aviso });
          }

          runtimesRef.current.delete(pendingId);
          lastSummaryRef.current.delete(pendingId);
          runtimesRef.current.set(created.session_id, runtime);
          idBox.current = created.session_id;
          activeIdRef.current = created.session_id;
          notify();

          void runtime.run();
        } catch (error) {
          runtime.errored = true;
          runtime.running = false;
          runtime.append({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
          // Mantém a entrada no mapa sob o próprio `pendingId` — sem isto, o
          // erro fica registrado numa sessão que ninguém mais referencia
          // (activeIdRef ainda aponta para pendingId), e a UI volta para a
          // tela de boas-vindas como se nada tivesse acontecido.
          notify();
        }
      })();
    },
    [project, onFileTouched, onNotify, notify, notifyFor],
  );

  const switchTo = useCallback(
    (sessionId: string | null) => {
      activeIdRef.current = sessionId;
      notify();
    },
    [notify],
  );

  const openClosedSession = useCallback(
    (sessionId: string, task = "") => {
      if (!project) return;
      if (runtimesRef.current.has(sessionId)) {
        switchTo(sessionId);
        return;
      }
      void AgentSessionRuntime.loadClosed(
        sessionId,
        { project, onChange: () => notifyFor(sessionId) },
        task,
      ).then((runtime) => {
        runtimesRef.current.set(sessionId, runtime);
        activeIdRef.current = sessionId;
        notify();
      });
    },
    [project, notify, notifyFor, switchTo],
  );

  const removeSession = useCallback(
    (sessionId: string) => {
      const runtime = runtimesRef.current.get(sessionId);
      runtime?.abort();
      runtimesRef.current.delete(sessionId);
      lastSummaryRef.current.delete(sessionId);
      if (activeIdRef.current === sessionId) {
        activeIdRef.current = null;
      }
      notify();
    },
    [notify],
  );

  const newSessionSlot = useCallback(() => {
    activeIdRef.current = null;
    notify();
  }, [notify]);

  const activeId = activeIdRef.current;
  const active = activeId ? (runtimesRef.current.get(activeId) ?? null) : null;

  const decideActive = useCallback((decisions: Record<string, boolean>) => {
    void active?.decide(decisions);
  }, [active]);

  const sessions = useMemo<SessionSummary[]>(() => {
    return Array.from(runtimesRef.current.entries()).map(([id, runtime]) => ({
      id,
      task: runtime.task || id,
      mode: "",
      branch: runtime.session?.branch ?? "",
      status: statusOf(runtime),
      closed: runtime.readOnly,
    }));
  }, [renderTick, activeId]);

  return {
    sessions,
    activeId,
    active,
    startSession,
    switchTo,
    openClosedSession,
    removeSession,
    newSessionSlot,
    decideActive,
  };
}
