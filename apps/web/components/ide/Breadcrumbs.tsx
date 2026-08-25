"use client";

import { useIde } from "@/lib/ide-store";
import { FileIcon } from "@/components/ide/FileIcons";

export function Breadcrumbs({ activePath }: { activePath?: string | null }) {
  const { project, setPanel, revealFolder } = useIde();

  const abrirNoExplorer = (path: string) => {
    setPanel("explorer");
    revealFolder(path);
  };

  if (!activePath) {
    return (
      <div className="ide-breadcrumbs">
        <span className="breadcrumb-segment project">{project || "NovaAI Studio"}</span>
      </div>
    );
  }

  const parts = activePath.split("/");
  const filename = parts.pop() || activePath;

  return (
    <nav className="ide-breadcrumbs" aria-label="Breadcrumb">
      <span className="breadcrumb-segment project">{project || "NovaAI Studio"}</span>

      {parts.map((part, index) => {
        const subPath = parts.slice(0, index + 1).join("/");
        return (
          <span key={subPath} className="breadcrumb-item">
            <span className="breadcrumb-sep">/</span>
            <button
              type="button"
              className="breadcrumb-segment folder breadcrumb-link"
              onClick={() => abrirNoExplorer(subPath)}
              title={`Mostrar "${part}" no Explorer`}
            >
              {part}
            </button>
          </span>
        );
      })}

      <span className="breadcrumb-item">
        <span className="breadcrumb-sep">/</span>
        <span className="breadcrumb-segment file active">
          <FileIcon filename={filename} className="breadcrumb-icon" />
          {filename}
        </span>
      </span>
    </nav>
  );
}
