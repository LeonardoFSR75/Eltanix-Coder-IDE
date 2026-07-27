/**
 * Modos do agente e suas descrições.
 *
 * Fonte única: usado tanto pelo indicador no input do chat quanto pela aba
 * "Agentes" do popover de Personalizações — os dois precisam mostrar
 * exatamente o mesmo texto, então duplicá-lo criaria divergência silenciosa.
 */

export type Mode = "ask" | "edit" | "agent" | "plan" | "auto";

export const MODE_HINT: Record<Mode, string> = {
  ask: "Só leitura: o agente responde sem tocar em nada.",
  edit: "Pode editar arquivos, mas não executar comandos.",
  agent: "Agente interativo: edita e roda testes pedindo aprovação.",
  plan: "Modo Planejar: gera um plano passo a passo detalhado antes de alterar arquivos.",
  auto: "Modo Automático: executa tarefas ponta a ponta autonomamente (edição, testes e fixes).",
};

export const MODES: Mode[] = ["plan", "auto", "ask", "edit", "agent"];
