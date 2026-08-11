"use client";

import { BlameCard } from "./BlameCard";
import { BrowserCard } from "./BrowserCard";
import { CodeReviewCard } from "./CodeReviewCard";
import { DiffCard } from "./DiffCard";
import { ExplorerCard } from "./ExplorerCard";
import { GitCard } from "./GitCard";
import { GraphCard } from "./GraphCard";
import { ListFilesCard, ReadFileCard } from "./ReadFileCard";
import { RunCommandCard } from "./RunCommandCard";
import { SearchCard } from "./SearchCard";
import type { ToolCardProps } from "./types";

const GIT_TOOLS = new Set(["git_status", "git_diff", "git_commit", "open_pull_request"]);

const DEDICATED_CARD_TOOLS = new Set([
  "read_file",
  "list_files",
  "write_file",
  "edit_file",
  "run_command",
  "search_code",
  "browser_action",
  "request_code_review",
  "code_history",
  "code_graph",
  "find_circular_imports",
  "find_orphan_modules",
]);

// `<ToolCallCard .../>` sempre produz um elemento React válido (mesmo quando
// o `case` cai em `default` e retorna `null` por dentro) — checar o valor de
// retorno do JSX para decidir "tem card dedicado?" é sempre verdadeiro e
// nunca cai no fallback genérico. Quem chama precisa perguntar isto ANTES de
// montar o elemento, não depois.
export function hasDedicatedCard(tool: string): boolean {
  return DEDICATED_CARD_TOOLS.has(tool) || GIT_TOOLS.has(tool);
}

// Ponto único de despacho: cada ferramenta nova só precisa aparecer aqui (e,
// se for um card de verdade — não o fallback do GIT_TOOLS — em
// `DEDICATED_CARD_TOOLS` acima). Ferramentas sem card dedicado caem no
// fallback (texto truncado, o comportamento de antes desta fase) em vez de
// quebrar a renderização.
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
    case "code_history":
      return <BlameCard {...props} />;
    case "code_graph":
      return <GraphCard {...props} />;
    case "find_circular_imports":
    case "find_orphan_modules":
      return <ExplorerCard {...props} />;
    default:
      if (GIT_TOOLS.has(props.tool)) return <GitCard {...props} />;
      return null;
  }
}
