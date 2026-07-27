"use client";

/**
 * Estado compartilhado do IDE.
 *
 * Um contexto único em vez de estado espalhado: o command palette precisa
 * abrir arquivos, o painel Git precisa saber qual aba está ativa, o quick open
 * precisa da lista de arquivos do projeto. Sem um ponto comum, cada painel
 * acabaria com sua própria cópia e elas divergiriam.
 *
 * A escolha de projeto e as abas abertas persistem no `localStorage` — reabrir
 * o editor e encontrar tudo fechado é a diferença entre uma ferramenta e uma
 * demonstração.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { get } from "@/lib/client";

export interface Project {
  name: string;
  path: string;
  is_git: boolean;
  branch: string | null;
}

export interface FileEntry {
  path: string;
  name: string;
  language: string | null;
  size_bytes: number;
}

export type PanelId = "explorer" | "search" | "git";

/** Onde posicionar o cursor ao abrir — usado por "ir para definição" e busca. */
export interface Reveal {
  path: string;
  line: number;
  column: number;
}

interface IdeState {
  project: string | null;
  projects: Project[];
  projectsError: string | null;
  setProject: (name: string) => void;
  reloadProjects: () => Promise<void>;

  tabs: string[];
  active: string | null;
  dirty: Set<string>;
  openFile: (path: string, reveal?: { line: number; column: number }) => void;
  /** Posição pendente. O editor consome e chama `clearReveal`. */
  reveal: Reveal | null;
  clearReveal: () => void;
  closeTab: (path: string) => void;
  setActive: (path: string | null) => void;
  markDirty: (path: string, isDirty: boolean) => void;

  panel: PanelId;
  setPanel: (panel: PanelId) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  terminalOpen: boolean;
  setTerminalOpen: (open: boolean) => void;

  // Dock do agente, à direita — persistente, independente da barra esquerda.
  agentDockOpen: boolean;
  setAgentDockOpen: (open: boolean) => void;
  toggleAgentDock: () => void;

  files: FileEntry[];
  reloadFiles: () => Promise<void>;

  // Incrementado quando algo muda no disco; painéis observam para recarregar.
  revision: number;
  bumpRevision: () => void;
}

const Ctx = createContext<IdeState | null>(null);

const STORAGE_KEY = "sicoobito.ide";

interface Persisted {
  project?: string | null;
  tabs?: string[];
  active?: string | null;
}

function load(): Persisted {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Persisted;
  } catch {
    return {};
  }
}

export function IdeProvider({ children }: { children: ReactNode }) {
  const [project, setProjectState] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [tabs, setTabs] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [panel, setPanelState] = useState<PanelId>("explorer");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [agentDockOpen, setAgentDockOpen] = useState(true);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [revision, setRevision] = useState(0);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [hydrated, setHydrated] = useState(false);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => !prev);
  }, []);

  const toggleAgentDock = useCallback(() => {
    setAgentDockOpen((prev) => !prev);
  }, []);

  const setPanel = useCallback((newPanel: PanelId) => {
    setPanelState(newPanel);
    setSidebarOpen(true);
  }, []);

  // A restauração acontece só no cliente: ler localStorage durante o render do
  // servidor causaria divergência de hidratação.
  useEffect(() => {
    const saved = load();
    if (saved.project) setProjectState(saved.project);
    if (saved.tabs?.length) setTabs(saved.tabs);
    if (saved.active) setActive(saved.active);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ project, tabs, active }));
  }, [hydrated, project, tabs, active]);

  const reloadProjects = useCallback(async () => {
    try {
      const data = await get<{ projects: Project[] }>("/api/projects");
      setProjects(data.projects);
      setProjectsError(null);
      // Um projeto salvo que sumiu do disco deixaria o IDE preso num estado
      // inválido; nesse caso caímos no primeiro disponível.
      setProjectState((atual) => {
        if (atual && data.projects.some((p) => p.name === atual)) return atual;
        return data.projects[0]?.name ?? null;
      });
    } catch (err) {
      setProjectsError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (hydrated) void reloadProjects();
  }, [hydrated, reloadProjects]);

  const reloadFiles = useCallback(async () => {
    if (!project) return;
    try {
      const data = await get<{ files: FileEntry[] }>(
        `/api/workspace/files?project=${encodeURIComponent(project)}`,
      );
      setFiles(data.files);
    } catch {
      setFiles([]);
    }
  }, [project]);

  useEffect(() => {
    void reloadFiles();
  }, [reloadFiles, revision]);

  const setProject = useCallback((name: string) => {
    setProjectState(name);
    // Trocar de projeto com abas de outro abertas mostraria arquivos que não
    // existem mais no contexto atual.
    setTabs([]);
    setActive(null);
    setDirty(new Set());
  }, []);

  const openFile = useCallback((path: string, posicao?: { line: number; column: number }) => {
    setTabs((prev) => (prev.includes(path) ? prev : [...prev, path]));
    setActive(path);
    // Guardado com o caminho junto: sem isso, abrir A e depois B faria o
    // cursor de B parar na linha pedida para A.
    setReveal(posicao ? { path, ...posicao } : null);
  }, []);

  const clearReveal = useCallback(() => setReveal(null), []);

  const closeTab = useCallback((path: string) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t !== path);
      setActive((atual) => (atual === path ? (next[next.length - 1] ?? null) : atual));
      return next;
    });
    setDirty((prev) => {
      const next = new Set(prev);
      next.delete(path);
      return next;
    });
  }, []);

  const markDirty = useCallback((path: string, isDirty: boolean) => {
    setDirty((prev) => {
      const next = new Set(prev);
      if (isDirty) next.add(path);
      else next.delete(path);
      return next;
    });
  }, []);

  const bumpRevision = useCallback(() => setRevision((r) => r + 1), []);

  const value = useMemo<IdeState>(
    () => ({
      project,
      projects,
      projectsError,
      setProject,
      reloadProjects,
      tabs,
      active,
      dirty,
      openFile,
      reveal,
      clearReveal,
      closeTab,
      setActive,
      markDirty,
      panel,
      setPanel,
      sidebarOpen,
      setSidebarOpen,
      toggleSidebar,
      terminalOpen,
      setTerminalOpen,
      agentDockOpen,
      setAgentDockOpen,
      toggleAgentDock,
      files,
      reloadFiles,
      revision,
      bumpRevision,
    }),
    [
      project, projects, projectsError, setProject, reloadProjects,
      tabs, active, dirty, openFile, reveal, clearReveal, closeTab, markDirty,
      panel, setPanel, sidebarOpen, toggleSidebar, terminalOpen,
      agentDockOpen, toggleAgentDock, files, reloadFiles, revision, bumpRevision,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useIde(): IdeState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useIde precisa estar dentro de <IdeProvider>");
  return ctx;
}

/**
 * Casamento fuzzy para o quick open.
 *
 * Pontua por proximidade dos caracteres: `rpol` acha `router/policy.py` porque
 * as letras aparecem em ordem e quase coladas. Sequências contíguas e o começo
 * de um segmento de caminho valem mais — é o que faz digitar o nome do arquivo
 * ganhar de um casamento espalhado no meio do caminho.
 */
export function fuzzyScore(alvo: string, consulta: string): number | null {
  if (!consulta) return 0;
  const alvoBaixo = alvo.toLowerCase();
  const consultaBaixa = consulta.toLowerCase();

  let pontos = 0;
  let indice = 0;
  let anterior = -1;

  for (const caractere of consultaBaixa) {
    const encontrado = alvoBaixo.indexOf(caractere, indice);
    if (encontrado === -1) return null;

    if (encontrado === anterior + 1) pontos += 8;
    if (encontrado === 0 || "/._-".includes(alvoBaixo[encontrado - 1] ?? "")) pontos += 6;
    // Penaliza a distância percorrida: casamentos espalhados valem menos.
    pontos -= Math.min(encontrado - indice, 10);

    anterior = encontrado;
    indice = encontrado + 1;
  }

  // Empate entre dois caminhos: o mais curto costuma ser o procurado.
  return pontos - alvo.length * 0.1;
}
