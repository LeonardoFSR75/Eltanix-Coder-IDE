"use client";

import { useEffect, useRef, useState } from "react";
import { AgentPanel } from "@/components/ide/AgentPanel";
import { useIde } from "@/lib/ide-store";
import { AgentChatInput } from "./AgentChatInput";
import { AgentDockHeader } from "./AgentDockHeader";
import { AgentManager } from "./AgentManager";
import { TodoCard } from "./cards";
import { CustomizationsPopover } from "./CustomizationsPopover";
import type { Mode } from "./modes";
import { useAgentSessions } from "./useAgentSessions";

export function AgentDock({
  onFileTouched,
  onSession,
}: {
  onFileTouched?: (path: string) => void;
  onSession?: (sessionId: string | null) => void;
}) {
  const { project, toggleAgentDock } = useIde();
  const {
    sessions,
    activeId,
    active,
    startSession,
    switchTo,
    openClosedSession,
    newSessionSlot,
  } = useAgentSessions({ project, onFileTouched });

  const [task, setTask] = useState("");
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

  const running = active?.running ?? false;

  const submitWithPrompt = (promptToRun?: string) => {
    const promptValue = promptToRun ?? task;
    if (!promptValue.trim() || running) return;
    startSession(promptValue, mode, profile, focusFiles, focusFolder);
    setSessionsVersion((v) => v + 1);
  };

  const handlePresetSelect = (presetPrompt: string) => {
    setTask(presetPrompt);
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
        <CustomizationsPopover anchorRef={settingsRef} onClose={() => setSettingsOpen(false)} />
      )}

      {!managerOpen && (
        <div className="agent-chat-body">
          {sessions.length > 1 && (
            <div className="agent-session-tabs">
              {sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`agent-session-tab ${s.status}${s.id === activeId ? " active" : ""}`}
                  onClick={() => switchTo(s.id)}
                  title={s.task}
                >
                  <span className={`session-status-dot ${s.status}`} />
                  <span className="agent-session-tab-label">{s.task}</span>
                </button>
              ))}
            </div>
          )}

          <AgentPanel
            session={active?.session ?? null}
            log={active?.log ?? []}
            pending={active?.readOnly ? [] : (active?.pending ?? [])}
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
            running={running}
            canSubmit={Boolean(task.trim() && project && !active?.readOnly)}
            onSubmit={() => submitWithPrompt()}
          />
        </div>
      )}
    </div>
  );
}
