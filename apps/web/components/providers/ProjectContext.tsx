"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { get } from "@/lib/client";
import { useAuth } from "@/components/providers/AuthContext";

/**
 * Projeto atual, compartilhado pela app inteira — o que a Central de
 * Projetos, o IDE e as páginas de domínio (RAG, Notas, Graphify, Requests)
 * todos leem/escrevem, em vez de cada um manter sua própria cópia (o problema
 * que motivou isto: o seletor do IDE e o da Central divergiam).
 *
 * Fonte da verdade: `GET /api/projects` (o router DB-backed, não a descoberta
 * de disco antiga) — mais rico que o shape que o IDE consumia sozinho.
 */

export interface ProjectRecordView {
  id: string;
  /** Identificador aceito pela API em `?project=`. */
  slug: string;
  /** Rótulo de exibição — nunca usar como identificador. */
  name: string;
  description: string;
  local_path: string | null;
  /** `false` quando a pasta de `local_path` não existe mais no disco (movida
   * ou apagada fora da IDE). O cadastro no Postgres não tem essa invariante,
   * então a lista pode conter projeto-fantasma (ver ADR 0016). */
  local_path_exists?: boolean;
  git_url: string | null;
  default_branch: string;
  budget_limit_usd: number | null;
  settings: Record<string, unknown>;
  my_role?: "viewer" | "editor" | "owner" | null;
}

interface ProjectContextType {
  /** SLUG do projeto ativo — nunca o `name` de exibição. É o identificador
   * que a API aceita (`?project=`), e a única coisa que vale guardar/propagar. */
  currentProject: string | null;
  projects: ProjectRecordView[];
  /** `true` depois da primeira resposta de `GET /api/projects` (com sucesso
   * ou erro) — quem escolhe um projeto padrão precisa distinguir "lista vazia
   * porque ainda não carregou" de "lista vazia porque não há projeto". */
  projectsLoaded: boolean;
  /** Mensagem da última falha de `GET /api/projects`, `null` se deu certo.
   * Antes o erro era engolido e cada consumidor via só uma lista vazia. */
  projectsError: string | null;
  setCurrentProject: (slug: string | null) => void;
  reloadProjects: () => Promise<void>;
}

const Ctx = createContext<ProjectContextType | undefined>(undefined);
const STORAGE_KEY = "eltanix_current_project";

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const [projects, setProjects] = useState<ProjectRecordView[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [currentProject, setCurrentProjectState] = useState<string | null>(null);

  const reloadProjects = useCallback(async () => {
    try {
      const data = await get<{ projects: ProjectRecordView[] }>("/api/projects");
      setProjects(data.projects);
      setProjectsError(null);
    } catch (err) {
      setProjects([]);
      setProjectsError(err instanceof Error ? err.message : String(err));
    } finally {
      setProjectsLoaded(true);
    }
  }, []);

  // `ProjectProvider` vive na raiz do app, ativo mesmo na tela de login —
  // sem sessão, `GET /api/projects` só dá 401. Recarrega quando o login
  // muda de nulo para um usuário (e limpa se deslogar), em vez de só na
  // montagem, que aconteceria antes de existir sessão nenhuma.
  useEffect(() => {
    if (user) void reloadProjects();
    else {
      setProjects([]);
      setProjectsError(null);
    }
  }, [user, reloadProjects]);

  // Query param manda quando presente (link direto/compartilhável tipo
  // `/rag?project=x`, ver Hub 360°); localStorage é só o fallback ao entrar
  // sem query param. `window.location.search` em vez de `useSearchParams()`
  // — mesmo padrão já usado por `AgentDock.tsx` para não exigir um limite
  // de Suspense em volta do provider (que fica na raiz do app).
  //
  // Depende de `pathname`: como este provider vive na raiz do layout e nunca
  // desmonta, um efeito com `deps=[]` só rodaria uma vez por sessão da SPA —
  // navegar via `<Link href="/ide?project=B">` a partir de outra página (ex.
  // Central de Projetos) trocaria a URL sem nunca reler o query param, e o
  // IDE abriria silenciosamente o projeto antigo. `usePathname()` muda a cada
  // navegação entre rotas (sem precisar de `useSearchParams()`/Suspense) e
  // por essa hora `window.location.search` já reflete a URL nova.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const fromQuery = new URLSearchParams(window.location.search).get("project");
    if (fromQuery) {
      setCurrentProjectState(fromQuery);
      window.localStorage.setItem(STORAGE_KEY, fromQuery);
    } else {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) setCurrentProjectState(stored);
    }
  }, [pathname]);

  const setCurrentProject = useCallback((slug: string | null) => {
    setCurrentProjectState(slug);
    if (typeof window === "undefined") return;
    if (slug) window.localStorage.setItem(STORAGE_KEY, slug);
    else window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  // Poda `currentProject` se ele não aparece na lista que acabou de carregar
  // — projeto apagado, ou o membership do usuário mudou desde que o slug foi
  // salvo no localStorage (ou veio de um link `?project=` velho). Sem isto,
  // cada consumidor (IDE, RAG, Notas, Graphify, Requests) batia 403/404
  // contra um slug morto, cada um sem saber que o motivo era esse. Só roda
  // depois que `projects` reflete de fato uma resposta do backend — antes
  // disso `projects` é só `[]` inicial, e podaria um slug válido à toa.
  //
  // `projectsError` também barra a poda: com a API fora do ar `projects` fica
  // `[]` sem que nada tenha sido apagado, e podar aqui faria o usuário perder
  // a seleção (e o IDE fechar o projeto) por causa de uma falha passageira.
  useEffect(() => {
    if (!projectsLoaded || projectsError || !currentProject) return;
    const aindaExiste = projects.some((p) => p.slug === currentProject);
    if (!aindaExiste) setCurrentProject(null);
  }, [projectsLoaded, projectsError, projects, currentProject, setCurrentProject]);

  return (
    <Ctx.Provider
      value={{
        currentProject,
        projects,
        projectsLoaded,
        projectsError,
        setCurrentProject,
        reloadProjects,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useProject(): ProjectContextType {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useProject deve ser usado dentro de <ProjectProvider>");
  return ctx;
}
