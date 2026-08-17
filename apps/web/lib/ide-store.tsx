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
 *
 * Editor em grupos (Fase 6): cada painel do split view é um `EditorGroup`
 * independente (abas, aba ativa, aba preview, dirty próprios); `layout`
 * descreve como os grupos se distribuem na tela (árvore de splits). Os
 * getters `tabs`/`active`/`dirty`/`previewTab` no topo do estado continuam
 * existindo e refletem o GRUPO ATIVO — é o que permite Explorer, Quick Open,
 * Command Palette, o painel do agente etc. continuarem chamando `openFile`
 * sem saber nada sobre grupos: eles sempre abrem "no grupo com foco agora",
 * exatamente como antes de existir mais de um grupo.
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
import { get, post } from "@/lib/client";
import { clearBuffer } from "@/lib/editor-buffer-cache";
import { useProject } from "@/components/providers/ProjectContext";

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

export type PanelId = "explorer" | "search" | "git" | "debug" | "browser" | "packages" | "extensions" | "containers" | "trello";

/** Onde posicionar o cursor ao abrir — usado por "ir para definição" e busca. */
export interface Reveal {
  path: string;
  line: number;
  column: number;
}

export interface EditorGroup {
  id: string;
  tabs: string[];
  active: string | null;
  previewTab: string | null;
  dirty: Set<string>;
}

export type PaneNode =
  | { type: "leaf"; groupId: string }
  | { type: "split"; id: string; direction: "row" | "column"; children: PaneNode[] };

export const DEFAULT_GROUP_ID = "main";

function newGroup(id: string): EditorGroup {
  return { id, tabs: [], active: null, previewTab: null, dirty: new Set() };
}

function insertSplit(
  node: PaneNode,
  targetGroupId: string,
  newGroupId: string,
  direction: "row" | "column",
): PaneNode {
  if (node.type === "leaf") {
    if (node.groupId !== targetGroupId) return node;
    // O id do split reaproveita o id do grupo novo (1:1, sempre criados
    // juntos aqui) — evita mais um gerador de id só pra isto.
    return { type: "split", id: newGroupId, direction, children: [node, { type: "leaf", groupId: newGroupId }] };
  }
  return { ...node, children: node.children.map((c) => insertSplit(c, targetGroupId, newGroupId, direction)) };
}

function removeGroupFromLayout(node: PaneNode, groupId: string): PaneNode | null {
  if (node.type === "leaf") return node.groupId === groupId ? null : node;
  const children = node.children
    .map((c) => removeGroupFromLayout(c, groupId))
    .filter((c): c is PaneNode => c !== null);
  if (children.length === 0) return null;
  // Só sobrou um lado do split: ele toma o lugar do nó de split inteiro, em
  // vez de deixar um grupo "sozinho dentro de um split de um item só".
  if (children.length === 1) return children[0];
  return { ...node, children };
}

function firstLeafGroupId(node: PaneNode): string {
  return node.type === "leaf" ? node.groupId : firstLeafGroupId(node.children[0]);
}

interface IdeState {
  project: string | null;
  projects: Project[];
  projectsError: string | null;
  setProject: (name: string) => void;
  reloadProjects: () => Promise<void>;
  createProject: (name: string, gitInit?: boolean) => Promise<Project>;

  /** Abas/ativa/dirty/preview do GRUPO ATIVO — ver nota no topo do arquivo. */
  tabs: string[];
  active: string | null;
  dirty: Set<string>;
  previewTab: string | null;

  /** Todo grupo aceita um `groupId` opcional; omitido, usa o grupo ativo. */
  openFile: (path: string, reveal?: { line: number; column: number }, groupId?: string) => void;
  previewFile: (path: string, reveal?: { line: number; column: number }, groupId?: string) => void;
  pinTab: (path: string, groupId?: string) => void;
  reorderTabs: (from: string, to: string, groupId?: string) => void;
  closeTab: (path: string, groupId?: string) => void;
  setActive: (path: string, groupId?: string) => void;
  markDirty: (path: string, isDirty: boolean, groupId?: string) => void;

  /** Posição pendente. O editor consome e chama `clearReveal`. */
  reveal: Reveal | null;
  clearReveal: () => void;

  /** Pasta pendente de revelação na árvore do Explorer (breadcrumb clicável
   * etc.) — mesmo padrão de `reveal`/`clearReveal`: o Explorer consome e
   * chama `clearRevealFolder` depois de expandir/rolar até ela. */
  revealFolderPath: string | null;
  revealFolder: (path: string) => void;
  clearRevealFolder: () => void;

  groups: Record<string, EditorGroup>;
  activeGroupId: string;
  layout: PaneNode;
  setActiveGroup: (groupId: string) => void;
  /** Proporção (0-100) de cada split arrastado, por `PaneNode.id` — vive só
   * na sessão, igual `layout` (ver comentário na hidratação): um reload
   * sempre volta a um único painel, então não há split pra reaplicar. */
  paneSplitRatios: Record<string, number>;
  setPaneSplitRatio: (splitId: string, ratio: number) => void;
  /** Cria um novo grupo na posição de `targetGroupId`, movendo `path` para
   * ele — de `sourceGroupId` (padrão: o próprio `targetGroupId`, o caso do
   * botão "Dividir" no editor) ou de outro grupo (arrastar uma aba até a
   * borda de um painel diferente). */
  splitGroup: (
    targetGroupId: string,
    path: string,
    direction?: "row" | "column",
    sourceGroupId?: string,
  ) => void;
  moveTabToGroup: (path: string, fromGroupId: string, toGroupId: string) => void;
  /** Sem efeito se `groupId` for o único grupo restante. */
  closeGroup: (groupId: string) => void;

  panel: PanelId;
  setPanel: (panel: PanelId) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  terminalOpen: boolean;
  setTerminalOpen: (open: boolean) => void;

  // Dock do agente
  agentDockOpen: boolean;
  setAgentDockOpen: (open: boolean) => void;
  toggleAgentDock: () => void;

  // Resizing e Layout
  sidebarWidth: number;
  setSidebarWidth: (width: number) => void;
  agentDockWidth: number;
  setAgentDockWidth: (width: number) => void;
  terminalHeight: number;
  setTerminalHeight: (height: number) => void;

  // Inserção de código via IA
  codeToInsert: { code: string; timestamp: number } | null;
  insertCode: (code: string) => void;
  clearInsertedCode: () => void;

  // Telemetria do Gateway Router
  routerLatency: number | null;
  routerStatus: "online" | "degraded" | "offline";
  checkRouterHealth: () => Promise<void>;

  files: FileEntry[];
  reloadFiles: () => Promise<void>;

  // Incrementado quando algo muda no disco; painéis observam para recarregar.
  revision: number;
  bumpRevision: () => void;

  // Um arquivo mudou no disco por fora do editor (ex.: a revisão de diff do
  // agente reverteu uma edição) — o Editor, se tiver aquele path aberto,
  // recarrega o conteúdo em vez de mostrar a versão antiga em memória.
  fileSyncVersion: Record<string, number>;
  notifyFileChanged: (path: string) => void;

  // Sessão ativa do agente para integração com o Monaco Editor
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
}


const Ctx = createContext<IdeState | null>(null);

const STORAGE_KEY = "sicoobito.ide";

interface Persisted {
  project?: string | null;
  tabs?: string[];
  active?: string | null;
  sidebarWidth?: number;
  agentDockWidth?: number;
  terminalHeight?: number;
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
  // Projeto atual é compartilhado com o resto da app (Central de Projetos,
  // HeaderNav) via `ProjectContext` — o IDE não guarda mais sua própria
  // fonte de verdade, só reage a ela e propaga de volta quando o usuário
  // troca de projeto por aqui (picker, Ctrl+O, criar projeto).
  const { currentProject: globalProject, setCurrentProject: setGlobalProject } = useProject();
  const [project, setProjectState] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [groups, setGroups] = useState<Record<string, EditorGroup>>(() => ({
    [DEFAULT_GROUP_ID]: newGroup(DEFAULT_GROUP_ID),
  }));
  const [activeGroupId, setActiveGroupIdState] = useState(DEFAULT_GROUP_ID);
  const [layout, setLayout] = useState<PaneNode>({ type: "leaf", groupId: DEFAULT_GROUP_ID });
  const [paneSplitRatios, setPaneSplitRatios] = useState<Record<string, number>>({});
  const [panel, setPanelState] = useState<PanelId>("explorer");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [agentDockOpen, setAgentDockOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const [agentDockWidth, setAgentDockWidth] = useState(360);
  const [terminalHeight, setTerminalHeight] = useState(220);
  const [codeToInsert, setCodeToInsert] = useState<{ code: string; timestamp: number } | null>(null);
  const [routerLatency, setRouterLatency] = useState<number | null>(null);
  const [routerStatus, setRouterStatus] = useState<"online" | "degraded" | "offline">("online");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [revision, setRevision] = useState(0);
  const [fileSyncVersion, setFileSyncVersion] = useState<Record<string, number>>({});
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [revealFolderPath, setRevealFolderPathState] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);


  const activeGroup = groups[activeGroupId] ?? Object.values(groups)[0] ?? newGroup(DEFAULT_GROUP_ID);

  const updateGroup = useCallback((groupId: string, updater: (g: EditorGroup) => EditorGroup) => {
    setGroups((prev) => {
      const g = prev[groupId];
      if (!g) return prev;
      return { ...prev, [groupId]: updater(g) };
    });
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => !prev);
  }, []);

  const toggleAgentDock = useCallback(() => {
    setAgentDockOpen((prev) => !prev);
  }, []);

  const insertCode = useCallback((code: string) => {
    setCodeToInsert({ code, timestamp: Date.now() });
  }, []);

  const clearInsertedCode = useCallback(() => setCodeToInsert(null), []);

  const checkRouterHealth = useCallback(async () => {
    const t0 = performance.now();
    try {
      await get("/api/health/providers");
      const elapsed = Math.round(performance.now() - t0);
      setRouterLatency(elapsed);
      setRouterStatus("online");
    } catch {
      setRouterLatency(null);
      setRouterStatus("offline");
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(() => void checkRouterHealth(), 30000);
    return () => clearInterval(timer);
  }, [checkRouterHealth]);

  const setPanel = useCallback((newPanel: PanelId) => {
    setPanelState(newPanel);
    setSidebarOpen(true);
  }, []);

  // A restauração acontece só no cliente. Só o grupo padrão é restaurado —
  // splits são de sessão, um reload sempre volta a um único painel.
  useEffect(() => {
    const saved = load();
    if (saved.project) setProjectState(saved.project);
    if (saved.tabs?.length || saved.active) {
      setGroups((prev) => ({
        ...prev,
        [DEFAULT_GROUP_ID]: {
          ...prev[DEFAULT_GROUP_ID],
          tabs: saved.tabs?.length ? saved.tabs : prev[DEFAULT_GROUP_ID].tabs,
          active: saved.active ?? prev[DEFAULT_GROUP_ID].active,
        },
      }));
    }
    if (saved.sidebarWidth) setSidebarWidth(saved.sidebarWidth);
    if (saved.agentDockWidth) setAgentDockWidth(saved.agentDockWidth);
    if (saved.terminalHeight) setTerminalHeight(saved.terminalHeight);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const principal = groups[DEFAULT_GROUP_ID];
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        project,
        tabs: principal?.tabs ?? [],
        active: principal?.active ?? null,
        sidebarWidth,
        agentDockWidth,
        terminalHeight,
      }),
    );
  }, [hydrated, project, groups, sidebarWidth, agentDockWidth, terminalHeight]);

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

  const setProject = useCallback(
    (name: string) => {
      setProjectState(name);
      setGlobalProject(name);
      // Trocar de projeto com abas/grupos de outro abertos mostraria arquivos
      // que não existem mais no contexto atual — volta para um painel só.
      setGroups({ [DEFAULT_GROUP_ID]: newGroup(DEFAULT_GROUP_ID) });
      setLayout({ type: "leaf", groupId: DEFAULT_GROUP_ID });
      setActiveGroupIdState(DEFAULT_GROUP_ID);
    },
    [setGlobalProject],
  );

  // Projeto trocado por fora do IDE (Central de Projetos, HeaderNav) —
  // reflete aqui, com o mesmo reset de abas/grupos de `setProject`.
  useEffect(() => {
    if (globalProject && globalProject !== project) setProject(globalProject);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalProject]);

  const createProject = useCallback(
    async (name: string, gitInit: boolean = false) => {
      const p = await post<Project & { created: boolean }>("/api/projects", {
        name,
        git_init: gitInit,
      });
      await reloadProjects();
      setProject(p.name);
      return p;
    },
    [reloadProjects, setProject],
  );

  useEffect(() => {
    // Um único bootstrap em vez de dois efeitos concorrentes: evita duas
    // idas à rede disputando a mesma conexão logo no primeiro paint.
    if (hydrated) void Promise.all([reloadProjects(), checkRouterHealth()]);
  }, [hydrated, reloadProjects, checkRouterHealth]);

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

  // Pré-aquecimento automático do projeto, sandbox e browser na inicialização
  useEffect(() => {
    if (!project) return;
    let cancel = false;
    void (async () => {
      try {
        const res = await post<{
          session_id?: string;
          sandbox_ready?: boolean;
          is_web_app?: boolean;
          web_prewarmed?: boolean;
        }>(`/api/projects/${encodeURIComponent(project)}/prewarm`);
        if (!cancel && res.session_id) {
          setActiveSessionId(res.session_id);
        }
      } catch {
        // Pré-aquecimento em segundo plano silencioso
      }
    })();
    return () => {
      cancel = true;
    };
  }, [project]);

  const openFile = useCallback(
    (path: string, posicao?: { line: number; column: number }, groupId?: string) => {
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => ({
        ...g,
        tabs: g.tabs.includes(path) ? g.tabs : [...g.tabs, path],
        active: path,
      }));
      setActiveGroupIdState(gid);
      // Guardado com o caminho junto: sem isso, abrir A e depois B faria o
      // cursor de B parar na linha pedida para A.
      setReveal(posicao ? { path, ...posicao } : null);
    },
    [activeGroupId, updateGroup],
  );

  // Clique único na árvore: abre em modo "preview", reaproveitando a mesma
  // aba a cada novo arquivo em vez de acumular uma por clique — só vira aba
  // permanente se o usuário editar o arquivo ou der duplo-clique nele.
  const previewFile = useCallback(
    (path: string, posicao?: { line: number; column: number }, groupId?: string) => {
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => {
        if (g.tabs.includes(path)) return { ...g, active: path };
        const tabs =
          g.previewTab && g.tabs.includes(g.previewTab)
            ? g.tabs.map((t) => (t === g.previewTab ? path : t))
            : [...g.tabs, path];
        return { ...g, tabs, previewTab: path, active: path };
      });
      setActiveGroupIdState(gid);
      setReveal(posicao ? { path, ...posicao } : null);
    },
    [activeGroupId, updateGroup],
  );

  const pinTab = useCallback(
    (path: string, groupId?: string) => {
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => (g.previewTab === path ? { ...g, previewTab: null } : g));
    },
    [activeGroupId, updateGroup],
  );

  const reorderTabs = useCallback(
    (from: string, to: string, groupId?: string) => {
      if (from === to) return;
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => {
        const fromIdx = g.tabs.indexOf(from);
        const toIdx = g.tabs.indexOf(to);
        if (fromIdx === -1 || toIdx === -1) return g;
        const tabs = [...g.tabs];
        tabs.splice(fromIdx, 1);
        tabs.splice(toIdx, 0, from);
        return { ...g, tabs };
      });
    },
    [activeGroupId, updateGroup],
  );

  const clearReveal = useCallback(() => setReveal(null), []);
  const revealFolder = useCallback((path: string) => setRevealFolderPathState(path), []);
  const clearRevealFolder = useCallback(() => setRevealFolderPathState(null), []);

  const closeTab = useCallback(
    (path: string, groupId?: string) => {
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => {
        const tabs = g.tabs.filter((t) => t !== path);
        const dirty = new Set(g.dirty);
        dirty.delete(path);
        return {
          ...g,
          tabs,
          dirty,
          active: g.active === path ? (tabs[tabs.length - 1] ?? null) : g.active,
          previewTab: g.previewTab === path ? null : g.previewTab,
        };
      });
    },
    [activeGroupId, updateGroup],
  );

  const setActiveTab = useCallback(
    (path: string, groupId?: string) => {
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => (g.tabs.includes(path) ? { ...g, active: path } : g));
      setActiveGroupIdState(gid);
    },
    [activeGroupId, updateGroup],
  );

  const markDirty = useCallback(
    (path: string, isDirty: boolean, groupId?: string) => {
      const gid = groupId ?? activeGroupId;
      updateGroup(gid, (g) => {
        const dirty = new Set(g.dirty);
        if (isDirty) dirty.add(path);
        else dirty.delete(path);
        // Editar uma aba preview a promove a permanente — mesmo comportamento
        // do VS Code: uma preview existe para "só olhar", não para editar.
        return { ...g, dirty, previewTab: isDirty && g.previewTab === path ? null : g.previewTab };
      });
    },
    [activeGroupId, updateGroup],
  );

  const setActiveGroup = useCallback((groupId: string) => setActiveGroupIdState(groupId), []);

  const setPaneSplitRatio = useCallback((splitId: string, ratio: number) => {
    setPaneSplitRatios((prev) => ({ ...prev, [splitId]: ratio }));
  }, []);

  const splitGroup = useCallback(
    (
      targetGroupId: string,
      path: string,
      direction: "row" | "column" = "row",
      sourceGroupId: string = targetGroupId,
    ) => {
      const newId = `group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
      setGroups((prev) => {
        const target = prev[targetGroupId];
        if (!target) return prev;
        const next: Record<string, EditorGroup> = { ...prev };
        const source = prev[sourceGroupId];
        if (source) {
          const remaining = source.tabs.filter((t) => t !== path);
          next[sourceGroupId] = {
            ...source,
            tabs: remaining,
            active: source.active === path ? (remaining[remaining.length - 1] ?? null) : source.active,
            previewTab: source.previewTab === path ? null : source.previewTab,
          };
        }
        next[newId] = { id: newId, tabs: [path], active: path, previewTab: null, dirty: new Set() };
        return next;
      });
      setLayout((prev) => insertSplit(prev, targetGroupId, newId, direction));
      setActiveGroupIdState(newId);
    },
    [],
  );

  const moveTabToGroup = useCallback((path: string, fromGroupId: string, toGroupId: string) => {
    if (fromGroupId === toGroupId) return;
    setGroups((prev) => {
      const from = prev[fromGroupId];
      const to = prev[toGroupId];
      if (!from || !to) return prev;
      const remaining = from.tabs.filter((t) => t !== path);
      return {
        ...prev,
        [fromGroupId]: {
          ...from,
          tabs: remaining,
          active: from.active === path ? (remaining[remaining.length - 1] ?? null) : from.active,
          previewTab: from.previewTab === path ? null : from.previewTab,
        },
        [toGroupId]: {
          ...to,
          tabs: to.tabs.includes(path) ? to.tabs : [...to.tabs, path],
          active: path,
        },
      };
    });
    setActiveGroupIdState(toGroupId);
  }, []);

  const closeGroup = useCallback(
    (groupId: string) => {
      const next = removeGroupFromLayout(layout, groupId);
      if (next === null) return; // não fecha o único grupo restante
      setLayout(next);
      setGroups((prev) => {
        const rest = { ...prev };
        delete rest[groupId];
        return rest;
      });
      setActiveGroupIdState((prevActive) => (prevActive === groupId ? firstLeafGroupId(next) : prevActive));
    },
    [layout],
  );

  const bumpRevision = useCallback(() => setRevision((r) => r + 1), []);

  const notifyFileChanged = useCallback((path: string) => {
    setFileSyncVersion((prev) => ({ ...prev, [path]: (prev[path] ?? 0) + 1 }));
    // Limpa o cache fora do React (editor-buffer-cache.ts) também: sem isso
    // o Editor acharia que já tem o conteúdo certo em memória e nunca
    // buscaria a versão nova do disco.
    if (project) clearBuffer(project, path);
  }, [project]);

  const value = useMemo<IdeState>(
    () => ({
      project,
      projects,
      projectsError,
      setProject,
      reloadProjects,
      createProject,
      tabs: activeGroup.tabs,
      active: activeGroup.active,
      dirty: activeGroup.dirty,
      previewTab: activeGroup.previewTab,
      openFile,
      previewFile,
      pinTab,
      reorderTabs,
      reveal,
      clearReveal,
      revealFolderPath,
      revealFolder,
      clearRevealFolder,
      closeTab,
      setActive: setActiveTab,
      markDirty,
      groups,
      activeGroupId,
      layout,
      setActiveGroup,
      paneSplitRatios,
      setPaneSplitRatio,
      splitGroup,
      moveTabToGroup,
      closeGroup,
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
      sidebarWidth,
      setSidebarWidth,
      agentDockWidth,
      setAgentDockWidth,
      terminalHeight,
      setTerminalHeight,
      codeToInsert,
      insertCode,
      clearInsertedCode,
      routerLatency,
      routerStatus,
      checkRouterHealth,
      files,
      reloadFiles,
      revision,
      bumpRevision,
      fileSyncVersion,
      notifyFileChanged,
      activeSessionId,
      setActiveSessionId,
    }),
    [
      project, projects, projectsError, setProject, reloadProjects, createProject,
      activeGroup, openFile, previewFile, pinTab, reorderTabs,
      reveal, clearReveal, revealFolderPath, revealFolder, clearRevealFolder, closeTab, setActiveTab, markDirty,
      groups, activeGroupId, layout, setActiveGroup, paneSplitRatios, setPaneSplitRatio, splitGroup, moveTabToGroup, closeGroup,
      panel, setPanel, sidebarOpen, toggleSidebar, terminalOpen,
      agentDockOpen, toggleAgentDock, sidebarWidth, agentDockWidth, terminalHeight,
      codeToInsert, insertCode, clearInsertedCode,
      routerLatency, routerStatus, checkRouterHealth, files, reloadFiles, revision, bumpRevision,
      fileSyncVersion, notifyFileChanged, activeSessionId, setActiveSessionId,
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
