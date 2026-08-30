# ADR 0013 — `apps/desktop` congelado até a IDE web cruzar a barra da Onda 1

**Status:** aceito · **Data:** 2026-08-29

## Contexto

A IDE existe em **duas implementações paralelas**:

- `apps/web/components/ide/` — React / Next.js 15, ~13k LOC, o produto
  principal (editor Monaco, terminal, Agent Dock, painéis, navegador interno).
- `apps/desktop/src/lib/` — Svelte 5 + Tauri, apelidado de "o lite". É um
  **porte manual** de `apps/web` — os próprios arquivos admitem em comentário
  (`sessionTypes.ts`, `modes.ts` dizem "porta de
  `apps/web/components/ide/agent/...`").

Nenhum ADR justifica essa duplicação, apesar de o `CLAUDE.md` raiz exigir ADR
para decisões arquiteturais. E o porte **já divergiu em silêncio**, sem teste
nem processo que force paridade — só disciplina manual:

- `apps/desktop/src/lib/agent/sessionTypes.ts` não tem `PendingAction.review`,
  `PendingAction.diff`, `StartupGuard`/`Session.startup_guard`, `ActivityEvent`,
  nem `RuntimeStatus`.
- Fases 2–8 do upgrade do agente (slash commands reais, gate humano do plano,
  regras de contexto por glob, menções `@`, modos customizáveis, Cmd+K inline,
  checkpoints/rewind) não existem no desktop.
- `apps/desktop/src/lib/api` cobre 4 domínios; `apps/web/lib/api` cobre ~27.

O inventário completo do que divergiu está em
[`docs/desktop_parity_gap.md`](../desktop_parity_gap.md).

O time já decidiu (memória `project-desktop-standby`, 2026-08-18) priorizar
completar **uma** implementação por vez — a web — antes de retomar o desktop.
Este ADR formaliza essa decisão, que até agora só existia como nota de memória.

## Decisão

**`apps/desktop` fica congelado (standby).** Sai do congelamento quando
`apps/web` cruzar a barra da **Onda 1** do roadmap ponta a ponta
(autocompletar inline, Cmd+K nível 2, busca semântica, inteligência de calha,
central de notificações — ver `docs/proposals/` / artifact do roadmap).

Enquanto congelado:

1. **Nenhum trabalho novo em `apps/desktop/**`** a menos que o dono do projeto
   peça explicitamente. Não é falta de prioridade percebida — é decisão
   deliberada.
2. **PRs que tocam os módulos espelhados de `apps/web`**
   (`components/ide/agent/{modes,sessionRuntime,sessionTypes}.ts`, `AgentDock`,
   `PaneLayout`, `StatusBar`, `TabStrip`, `Terminal`, `TopMenuBar`,
   `InlineDiffApprovalBar`, `Editor`, `AgentManager`) **não precisam
   sincronizar o desktop**. O gap que isso acumula é esperado.
3. **O gap acumulado é rastreado em `docs/desktop_parity_gap.md`** e fechado de
   uma vez quando o desktop for retomado — não redescoberto item a item.
4. **O serviço `desktop` no `docker-compose.yml` (preview em :5409)
   permanece.** Congelar é sobre não investir, não sobre remover: o preview
   continua subindo para quem quiser inspecionar o estado atual.

Ao retomar, a ordem é: sincronizar `sessionTypes.ts`/`modes.ts` primeiro
(base de tudo), portar `sessionRuntime.ts` (a versão web já tem `rewind`,
marcador `@` e resolução de slash embutidos), depois as Fases na ordem de
dependência de UX (2 → 3 → 8; 4/5/6/7 em qualquer ordem).

## Alternativas consideradas

- **Manter os dois em paralelo com sincronização manual disciplinada** — é
  exatamente o que já falhou: divergiu sem nenhum teste que forçasse paridade.
  Manter o modelo que produziu o problema não o resolve.
- **Teste de contrato de paridade sobre `sessionTypes.ts`/`modes.ts` + manter
  os dois vivos** — resolve a divergência silenciosa, mas mantém o custo de
  evoluir duas UIs em dois frameworks enquanto a IDE web ainda muda rápido a
  cada onda. Reavaliar quando `apps/web` estabilizar (pós-Onda 1) — pode ser
  o caminho de saída do congelamento em vez de retomar o porte manual.
- **Deletar `apps/desktop`** — descartado. Um shell Tauri nativo (baixo
  consumo de RAM, distribuição desktop) é uma direção de produto válida; só
  não é a prioridade agora. Congelar preserva a opção sem custo de manutenção.
- **Unificar num framework só** (portar a web para Svelte, ou o desktop para
  Electron/React) — reescrita grande, sem retorno enquanto o foco é completar
  a experiência agêntica da web. Fora de escopo deste ADR.

## Consequências

- README e `docs/architecture.md` já marcam o desktop como 🔴 Experimental —
  consistente com este ADR; a linha ganha a nota "congelado por decisão
  (ADR 0013)".
- Contribuições externas para o desktop devem saber que ele **não está em
  paridade** e que isso é deliberado — não um bug a corrigir por PR avulso.
- `docs/desktop_parity_gap.md` passa a referenciar este ADR como a decisão
  que ele operacionaliza.
- O gatilho de saída é objetivo (Onda 1 entregue em `apps/web`), não uma data
  — evita o congelamento virar limbo indefinido.
