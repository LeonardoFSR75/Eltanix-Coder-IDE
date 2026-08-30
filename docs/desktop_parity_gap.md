# `apps/desktop` — Gap de Paridade com `apps/web` (Fases 2–8 do agente)

**Status:** rastreado, não acionável agora. `apps/desktop` (Svelte 5 + Tauri,
"o lite") está **congelado** por [ADR 0013](adr/0013-apps-desktop-congelado.md)
— sai do standby quando `apps/web` cruzar a barra da Onda 1 do roadmap ponta a
ponta. Ver também a nota de memória `project-desktop-standby` /
`review_ide_dual_implementation`. Este documento é o inventário que o ADR 0013
manda fechar de uma vez na retomada.

O desktop é um **porte manual** de `apps/web` (os próprios arquivos admitem em
comentário: `sessionTypes.ts`, `modes.ts` dizem "porta de
apps/web/components/ide/agent/..."). Não há teste nem processo que force
paridade — só disciplina. Este documento é o inventário do que divergiu, para
o gap ser fechado de uma vez quando o desktop voltar a ser trabalhado, em vez
de ser redescoberto.

Última conferência: 2026-08-29.

## Tipos ausentes em `apps/desktop/src/lib/agent/sessionTypes.ts`

| Tipo / campo | Web tem | Desktop |
|---|---|---|
| `PendingAction.review` (`{verdict, summary}` — 2ª opinião) | sim | **falta** |
| `PendingAction.diff` | sim | **falta** |
| `StartupGuard` (interface) + `Session.startup_guard` | sim | **falta** |
| `ActivityEvent` (interface) | sim | **falta** |
| `RuntimeStatus` (`idle`/`running`/`awaiting_approval`/`done`/`error`/`closed`) | sim | **falta** (só `SessionStatus` derivado) |
| `SessionSummary.closed` / campos extras | sim | parcial |

## Features de Fase ausentes no desktop

| Fase | Feature | Web | Desktop |
|---|---|---|---|
| 2 | Slash commands reais (`listSlashCommands`, autocomplete no input) | sim | **falta** — sem `lib/api` de slash, sem menu |
| 3 | Gate humano do plano (`write_todos` → aprovação, card "Revisar plano") | sim | **falta** — `sessionRuntime` não trata o caso |
| 4 | Regras de contexto por glob (`lib/api/contextRules`, aba no popover) | sim | **falta** |
| 5 | Menções `@` de contexto (`@arquivo`, `@docs`, `@web`) | sim | **falta** — sem detecção de `@` no input |
| 6 | Modos customizáveis (`lib/api/customModes`, seção "Meus modos") | sim | **falta** — `Mode` fixo nos 7, sem CRUD |
| 7 | Edição inline Cmd+K (`lib/api/inlineEdit`, widget no editor) | sim | **falta** |
| 8 | Checkpoints / rewind (`sessionRuntime.rewind()`, lista de checkpoints, "restaurar aqui") | sim | **falta** |

## Componentes/módulos de agente só no web

`AgentDockHeader`, `AgentManager`, `ModelPicker`, `UnifiedDiffPreview`,
`CustomizationsPopover`, `InlineDiffApprovalBar`, e todos os
`agent/cards/*` (`BlameCard`, `BrowserCard`, `CodeReviewCard`, `DiffCard`,
`ExplorerCard`, `GitCard`, `GraphCard`, `PackagesCard`, `ReadFileCard`,
`RunCommandCard`, `SearchCard`, `TodoCard`, `ToolCallCard`) — o desktop
renderiza tool output de forma bem mais simples.

`lib/api` só tem `agent`, `git`, `projects`, `workspace` (web tem ~27 domínios).

## Ao retomar o desktop

1. Sincronizar `sessionTypes.ts` e `modes.ts` primeiro (base de tudo).
2. Portar `sessionRuntime.ts` (a versão web já tem `rewind`, `@`-marker,
   slash resolution embutidos no fluxo).
3. Fases na ordem 2 → 3 → 8 (dependência de UX) e 4/5/6/7 em qualquer ordem.
