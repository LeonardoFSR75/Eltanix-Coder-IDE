/**
 * Modos do agente e suas descrições — porta de
 * `apps/web/components/ide/agent/modes.ts`. Fonte única entre o indicador do
 * chat e qualquer seletor de modo: os dois precisam mostrar exatamente o
 * mesmo texto do hub, senão divergem em silêncio.
 */

export type Mode = "ask" | "edit" | "agent" | "plan" | "auto" | "orchestra" | "explore";

export const MODE_HINT: Record<Mode, string> = {
  ask: "Só leitura: o agente responde sem tocar em nada.",
  edit: "Pode editar arquivos, mas não executar comandos.",
  agent: "Agente interativo: edita e roda testes pedindo aprovação.",
  plan: "Modo Planejar: gera um plano passo a passo detalhado antes de alterar arquivos.",
  auto: "Modo Automático: executa tarefas ponta a ponta autonomamente (edição, testes e fixes).",
  orchestra:
    "Modo Orquestra: planeja, implementa com TDD (teste falha → implementa → teste passa), " +
    "pede uma segunda opinião do modelo antes de cada commit, e commita a cada etapa aprovada.",
  explore:
    "Modo Explorar: só leitura, focado em arquitetura — grafo de código, histórico e " +
    "detecção de dependência circular/módulo órfão, sempre citando evidência.",
};

export const MODES: Mode[] = ["plan", "orchestra", "auto", "explore", "ask", "edit", "agent"];
