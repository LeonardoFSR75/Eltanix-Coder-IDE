"use client";

import { useRef, useState } from "react";
import { AgentPanel } from "@/components/ide/AgentPanel";
import { useIde } from "@/lib/ide-store";
import { AgentChatInput } from "./AgentChatInput";
import { AgentDockHeader } from "./AgentDockHeader";
import { AgentSessionList } from "./AgentSessionList";
import { CustomizationsPopover } from "./CustomizationsPopover";
import type { Mode } from "./modes";
import { useAgentSession } from "./useAgentSession";

export function AgentDock({
  onFileTouched,
  onSession,
}: {
  onFileTouched?: (path: string) => void;
  onSession?: (sessionId: string | null) => void;
}) {
  const { project, toggleAgentDock } = useIde();
  const { session, log, pending, running, start, decide, resetForNewSession } = useAgentSession({
    project,
    onFileTouched,
    onSession,
  });

  const [task, setTask] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [profile, setProfile] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sessionsVersion, setSessionsVersion] = useState(0);
  const settingsRef = useRef<HTMLButtonElement>(null);

  const submit = () => {
    if (!task.trim() || running) return;
    void start(task, mode, profile);
    setSessionsVersion((v) => v + 1);
  };

  return (
    <div className="agent">
      <AgentDockHeader
        historyOpen={historyOpen}
        onToggleHistory={() => setHistoryOpen((v) => !v)}
        onNewSession={() => {
          resetForNewSession();
          setTask("");
          setHistoryOpen(false);
        }}
        onOpenSettings={() => setSettingsOpen((v) => !v)}
        onCollapse={() => toggleAgentDock()}
        settingsRef={settingsRef}
      />

      {historyOpen && (
        <AgentSessionList
          project={project}
          refreshKey={sessionsVersion}
          onClose={() => setHistoryOpen(false)}
          onPickTask={(pickedTask, pickedMode, pickedProfile) => {
            setTask(pickedTask);
            if (["ask", "edit", "agent", "plan", "auto"].includes(pickedMode)) {
              setMode(pickedMode as Mode);
            }
            setProfile(pickedProfile);
            setHistoryOpen(false);
          }}
        />
      )}

      {settingsOpen && (
        <CustomizationsPopover anchorRef={settingsRef} onClose={() => setSettingsOpen(false)} />
      )}

      {!historyOpen && (
        <>
          <AgentChatInput
            task={task}
            setTask={setTask}
            mode={mode}
            setMode={setMode}
            profile={profile}
            setProfile={setProfile}
            running={running}
            canSubmit={Boolean(task.trim() && project)}
            onSubmit={submit}
          />
          <AgentPanel session={session} log={log} pending={pending} onDecide={decide} />
        </>
      )}
    </div>
  );
}
