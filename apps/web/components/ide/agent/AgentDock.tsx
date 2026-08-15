"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentPanel } from "@/components/ide/AgentPanel";
import { useToast } from "@/components/Toast";
import { useIde } from "@/lib/ide-store";
import { loadHookPrefs } from "@/lib/hook-prefs";
import { AgentChatInput } from "./AgentChatInput";
import { AgentDockHeader } from "./AgentDockHeader";
import { AgentManager } from "./AgentManager";
import { TodoCard } from "./cards";
import { CustomizationsPopover } from "./CustomizationsPopover";
import type { Mode } from "./modes";
import type { NotifyKind } from "./sessionRuntime";
import { useAgentSessions } from "./useAgentSessions";

export function AgentDock({
  onFileTouched,
  onSession,
}: {
  onFileTouched?: (path: string) => void;
  onSession?: (sessionId: string | null) => void;
}) {
  const { project, toggleAgentDock, groups, activeGroupId } = useIde();
  const { addToast } = useToast();


  // Hooks mínimos (aba "Hooks" do popover): lê a preferência do localStorage
  // a cada evento em vez de assinar mudanças — é uma leitura síncrona barata,
  // e evita re-renderizar o dock quando o usuário mexe nas preferências numa
  // sessão que já está rodando.
  const handleAgentNotify = useCallback(
    (kind: NotifyKind, message: string) => {
      const prefs = loadHookPrefs();
      if (kind === "approval" && !prefs.notifyApproval) return;
      if (kind === "done" && !prefs.notifyDone) return;
      if (kind === "error" && !prefs.notifyError) return;
      const toastType = kind === "approval" ? "info" : kind === "done" ? "success" : "error";
      addToast(message, toastType);
    },
    [addToast],
  );

  const {
    sessions,
    activeId,
    active,
    startSession,
    switchTo,
    openClosedSession,
    removeSession,
    newSessionSlot,
  } = useAgentSessions({ project, onFileTouched, onNotify: handleAgentNotify });

  const [task, setTask] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>("auto");
  const [profile, setProfile] = useState<string | null>(null);
  const [focusFiles, setFocusFiles] = useState<string[]>([]);
  const [focusFolder, setFocusFolder] = useState<string | null>(null);
  const [managerOpen, setManagerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sessionsVersion, setSessionsVersion] = useState(0);
  const settingsRef = useRef<HTMLButtonElement>(null);


  // O terminal reaproveita o sandbox da sessão do agente — segue a sessão
  // ativa no Agent Manager, não só a primeira criada.
  useEffect(() => {
    onSession?.(active?.session?.session_id ?? null);
  }, [active, onSession]);

  // Outras páginas (ex.: /rag) linkam para cá com `?agentPrompt=` para
  // pré-preencher uma pergunta sem duplicar o loop de chat aqui — a busca
  // real já é uma ferramenta que o próprio agente chama. Lido direto de
  // `window.location` (não `next/navigation`) para não exigir um Suspense
  // boundary só por causa deste prefill único no mount.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const prompt = params.get("agentPrompt");
    if (!prompt) return;
    setTask(prompt);
    params.delete("agentPrompt");
    const query = params.toString();
    const { pathname } = window.location;
    window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const running = active?.running ?? false;
  const awaitingApproval = (active?.pending.length ?? 0) > 0;

  const canSubmitActivePrompt = active ? active.canSubmit : Boolean(project);

  const submitWithPrompt = (promptToRun?: string) => {
    const promptValue = promptToRun ?? task;
    if ((!promptValue.trim() && images.length === 0) || !canSubmitActivePrompt || awaitingApproval) return;
    if (active && active.session && !active.readOnly) {
      void active.sendMessage(promptValue, images);
    } else {
      const activeTabs = groups[activeGroupId]?.tabs ?? [];
      const filesToPass = focusFiles.length > 0 ? focusFiles : activeTabs;
      startSession(promptValue, mode, profile, filesToPass, focusFolder, images);
      setSessionsVersion((v) => v + 1);
    }
    setTask("");
    setImages([]);
  };


  const handlePresetSelect = (presetPrompt: string) => {
    submitWithPrompt(presetPrompt);
  };

  return (
    <div className="agent-dock-layout">
      <AgentDockHeader
        historyOpen={managerOpen}
        onToggleHistory={() => setManagerOpen((v) => !v)}
        onNewSession={() => {
          newSessionSlot();
          setTask("");
          setFocusFiles([]);
          setFocusFolder(null);
          setManagerOpen(false);
        }}
        onOpenSettings={() => setSettingsOpen((v) => !v)}
        onCollapse={() => toggleAgentDock()}
        settingsRef={settingsRef}
      />

      {managerOpen && (
        <AgentManager
          project={project}
          refreshKey={sessionsVersion}
          liveSessions={sessions}
          activeId={activeId}
          onOpenLive={(id) => {
            switchTo(id);
            setManagerOpen(false);
          }}
          onOpenClosed={(id, taskText) => {
            openClosedSession(id, taskText);
            setManagerOpen(false);
          }}
          onClose={() => setManagerOpen(false)}
        />
      )}

      {settingsOpen && (
        <CustomizationsPopover
          anchorRef={settingsRef}
          onClose={() => setSettingsOpen(false)}
          mode={mode}
          setMode={setMode}
          project={project}
        />
      )}

      {!managerOpen && (
        <div className="agent-chat-body">
          {sessions.length > 1 && (
            <div className="agent-session-tabs">
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`agent-session-tab ${s.status}${s.id === activeId ? " active" : ""}`}
                  onClick={() => switchTo(s.id)}
                  title={s.task}
                  style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "6px" }}
                >
                  <span className={`session-status-dot ${s.status}`} />
                  <span className="agent-session-tab-label">{s.task}</span>
                  <button
                    type="button"
                    className="agent-session-tab-close"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSession(s.id);
                    }}
                    title="Fechar esta sessão"
                    style={{
                      background: "none",
                      border: "none",
                      color: "var(--muted)",
                      cursor: "pointer",
                      fontSize: "13px",
                      lineHeight: 1,
                      padding: "0 2px",
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <AgentPanel
            session={active?.session ?? null}
            log={active?.log ?? []}
            pending={active?.readOnly ? [] : (active?.pending ?? [])}
            running={running}
            activity={active?.currentActivity ?? null}
            recentActivities={active?.recentActivities ?? []}
            readOnly={active?.readOnly}
            onDecide={(decisions) => void active?.decide(decisions)}
            onPresetSelect={handlePresetSelect}
          />
          <TodoCard todos={active?.todos ?? []} />
          <AgentChatInput
            task={task}
            setTask={setTask}
            mode={mode}
            setMode={setMode}
            profile={profile}
            setProfile={setProfile}
            focusFiles={focusFiles}
            setFocusFiles={setFocusFiles}
            focusFolder={focusFolder}
            setFocusFolder={setFocusFolder}
            images={images}
            setImages={setImages}
            running={running || awaitingApproval}
            canSubmit={Boolean(
              (task.trim() || images.length > 0) &&
                project &&
                !active?.readOnly &&
                !awaitingApproval &&
                !running &&
                (active ? active.canSubmit : true),
            )}
            onSubmit={() => submitWithPrompt()}
            sessionStarted={Boolean(active?.session)}
          />
        </div>
      )}
    </div>
  );
}
