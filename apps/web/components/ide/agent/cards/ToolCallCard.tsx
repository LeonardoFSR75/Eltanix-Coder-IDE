"use client";

import { BrowserCard } from "./BrowserCard";
import { CodeReviewCard } from "./CodeReviewCard";
import { DiffCard } from "./DiffCard";
import { GitCard } from "./GitCard";
import { ListFilesCard, ReadFileCard } from "./ReadFileCard";
import { RunCommandCard } from "./RunCommandCard";
import { SearchCard } from "./SearchCard";
import type { ToolCardProps } from "./types";

const GIT_TOOLS = new Set(["git_status", "git_diff", "git_commit", "open_pull_request"]);

// Ponto único de despacho: cada ferramenta nova só precisa aparecer aqui.
// Ferramentas sem card dedicado caem no fallback (texto truncado, o
// comportamento de antes desta fase) em vez de quebrar a renderização.
export function ToolCallCard(props: ToolCardProps & { sessionId: string | null }) {
  switch (props.tool) {
    case "read_file":
      return <ReadFileCard {...props} />;
    case "list_files":
      return <ListFilesCard {...props} />;
    case "write_file":
    case "edit_file":
      return <DiffCard {...props} />;
    case "run_command":
      return <RunCommandCard {...props} />;
    case "search_code":
      return <SearchCard {...props} />;
    case "browser_action":
      return <BrowserCard {...props} />;
    case "request_code_review":
      return <CodeReviewCard {...props} />;
    default:
      if (GIT_TOOLS.has(props.tool)) return <GitCard {...props} />;
      return null;
  }
}
