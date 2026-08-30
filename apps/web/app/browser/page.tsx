"use client";

import { useProject } from "@/components/providers/ProjectContext";
import { EditorBrowserView } from "@/components/ide/EditorBrowserView";
import { IdeProvider } from "@/lib/ide-store";

export default function StandaloneBrowserPage() {
  const { currentProject } = useProject();

  return (
    <div className="browser-page-layout" style={{ height: "calc(100vh - 56px)", display: "flex", flexDirection: "column" }}>
      {/* `EditorBrowserView` lê `activeSessionId` via `useIde()` — fora do
          `/ide` (que já tem o provider no seu próprio page.tsx) esta rota
          standalone precisa fornecê-lo, senão `useIde()` lança e o Next
          troca a página inteira pela tela "Application error". */}
      <IdeProvider>
        <EditorBrowserView
          initialUrl="http://localhost:5400"
          sessionId={currentProject ? `browser-${currentProject}` : "browser-global"}
          isStandalone={true}
        />
      </IdeProvider>
    </div>
  );
}
