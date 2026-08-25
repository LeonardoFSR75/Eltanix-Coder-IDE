/**
 * Preferências de notificação da aba "Hooks" — versão mínima: só decide se um
 * evento que já chega pelo SSE da sessão (aprovação pendente, sessão
 * concluída, erro de ferramenta) vira um toast. Nenhuma execução de código,
 * nenhum estado no backend — por isso vive só no localStorage, mesmo padrão
 * de lib/theme.tsx.
 */

const STORAGE_KEY = "novaai_studio.hookPrefs";

export interface HookPrefs {
  notifyApproval: boolean;
  notifyDone: boolean;
  notifyError: boolean;
}

const DEFAULTS: HookPrefs = {
  notifyApproval: true,
  notifyDone: true,
  notifyError: true,
};

export function loadHookPrefs(): HookPrefs {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<HookPrefs>;
    return { ...DEFAULTS, ...saved };
  } catch {
    return DEFAULTS;
  }
}

export function saveHookPrefs(prefs: HookPrefs): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}
