"use client";

import { useProject } from "@/components/providers/ProjectContext";
import { EditorBrowserView } from "@/components/ide/EditorBrowserView";

export default function StandaloneBrowserPage() {
  const { currentProject } = useProject();

  return (
    <div className="browser-page-layout" style={{ height: "calc(100vh - 56px)", display: "flex", flexDirection: "column" }}>
      <EditorBrowserView
        initialUrl="http://localhost:5400"
        sessionId={currentProject ? `browser-${currentProject}` : "browser-global"}
        isStandalone={true}
      />
    </div>
  );
}
