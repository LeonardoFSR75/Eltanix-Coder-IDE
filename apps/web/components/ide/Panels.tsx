"use client";

/**
 * Painéis da barra lateral: Explorer, Busca e Git.
 *
 * Ficam juntos porque compartilham a mesma moldura e o mesmo estado de projeto;
 * separá-los em arquivos renderia três cabeçalhos e três tratamentos de erro
 * praticamente iguais.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { browserAction, closeBrowserSession } from "@/lib/api/browser";
import {
  createEntry,
  deleteEntry,
  listTree,
  moveEntry,
  replaceInWorkspace,
  searchWorkspace,
  type WorkspaceEntry as Entry,
} from "@/lib/api/workspace";
import {
  checkoutBranch,
  commitChanges,
  getGitBranches,
  getGitStatus,
  stageFiles,
  unstageFiles,
  type GitFile,
} from "@/lib/api/git";
import {
  getProjectPackages,
  installProjectPackage,
  uninstallProjectPackage,
  syncProjectRequirements,
  type PackageItem,
} from "@/lib/api/packages";
import {
  getContainerTree,
  runContainerAction,
  getContainerLogs,
  type ContainerTreeResponse,
  type ContainerItem,
} from "@/lib/api/containers";
import { useIde } from "@/lib/ide-store";

import { ConfirmDialog, PromptDialog } from "@/components/ide/Overlays";
import { FileIcon } from "@/components/ide/FileIcons";

// ── Explorer ────────────────────────────────────────────────────────────────

export function Explorer() {
  const { project, openFile, previewFile, pinTab, active, bumpRevision, revision, closeTab, tabs } = useIde();
  const [levels, setLevels] = useState<Record<string, Entry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lastClicked, setLastClicked] = useState<string | null>(null);
  const [dragOverPath, setDragOverPath] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [filterText, setFilterText] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number; entry: Entry | null } | null>(null);
  const [dialogo, setDialogo] = useState<
    | { tipo: "novo-arquivo" | "nova-pasta" | "renomear"; base: string; inicial: string }
    | { tipo: "excluir"; alvo: Entry }
    | { tipo: "excluir-lote"; alvos: string[] }
    | null
  >(null);
  const treeRef = useRef<HTMLDivElement>(null);

  const carregar = useCallback(
    async (subpath: string) => {
      if (!project) return;
      try {
        const entries = await listTree(project, subpath);
        setLevels((prev) => ({ ...prev, [subpath]: entries }));
        setErro(null);
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
      }
    },
    [project],
  );

  useEffect(() => {
    if (!project) return;
    setLevels({});
    void carregar(".");
    for (const dir of expanded) void carregar(dir);
  }, [project, carregar, revision]);

  // Revela o arquivo ativo: expande as pastas-pai (navegação por "ir para
  // definição", Quick Open etc. não passa pelo clique na árvore, então sem
  // isto o arquivo abriria sem a árvore acompanhar).
  useEffect(() => {
    if (!active) return;
    const partes = active.split("/");
    partes.pop();
    let acumulado = "";
    const paraExpandir: string[] = [];
    for (const parte of partes) {
      acumulado = acumulado ? `${acumulado}/${parte}` : parte;
      paraExpandir.push(acumulado);
    }
    if (paraExpandir.length === 0) return;

    setExpanded((prev) => {
      const next = new Set(prev);
      let mudou = false;
      for (const dir of paraExpandir) {
        if (!next.has(dir)) {
          next.add(dir);
          mudou = true;
        }
      }
      return mudou ? next : prev;
    });
    for (const dir of paraExpandir) {
      if (!levels[dir]) void carregar(dir);
    }
    // Só reage à troca do arquivo ativo — `levels`/`carregar` mudando não
    // deve reexpandir tudo de novo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    if (!active || !treeRef.current) return;
    const seletor = `[data-path="${CSS.escape(active)}"]`;
    treeRef.current.querySelector(seletor)?.scrollIntoView({ block: "nearest" });
  }, [active, levels, expanded]);

  // Ordem visual atual (mesmos filtros de `renderar`), usada só para
  // resolver o intervalo de um shift-click — não vale a pena manter em
  // estado, a árvore raramente passa de algumas centenas de linhas visíveis.
  const ordemVisivel = useCallback((): string[] => {
    const out: string[] = [];
    const percorrer = (subpath: string) => {
      const list = levels[subpath] ?? [];
      const filtered = filterText
        ? list.filter((e) => e.name.toLowerCase().includes(filterText.toLowerCase()) || e.is_dir)
        : list;
      for (const entry of filtered) {
        out.push(entry.path);
        if (entry.is_dir && expanded.has(entry.path)) percorrer(entry.path);
      }
    };
    percorrer(".");
    return out;
  }, [levels, filterText, expanded]);

  const alternar = (entry: Entry, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(entry.path)) next.delete(entry.path);
        else next.add(entry.path);
        return next;
      });
      setLastClicked(entry.path);
      return;
    }
    if (e.shiftKey && lastClicked) {
      const ordem = ordemVisivel();
      const i1 = ordem.indexOf(lastClicked);
      const i2 = ordem.indexOf(entry.path);
      if (i1 !== -1 && i2 !== -1) {
        const [ini, fim] = i1 < i2 ? [i1, i2] : [i2, i1];
        setSelected(new Set(ordem.slice(ini, fim + 1)));
        return;
      }
    }

    setSelected(new Set([entry.path]));
    setLastClicked(entry.path);

    if (!entry.is_dir) {
      // Clique único abre em "preview" (substitui a aba preview anterior);
      // duplo-clique (abaixo) fixa.
      previewFile(entry.path);
      return;
    }
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(entry.path)) next.delete(entry.path);
      else {
        next.add(entry.path);
        if (!levels[entry.path]) void carregar(entry.path);
      }
      return next;
    });
  };

  const pastaDe = (entry: Entry | null): string => {
    if (!entry) return "";
    if (entry.is_dir) return entry.path;
    const corte = entry.path.lastIndexOf("/");
    return corte === -1 ? "" : entry.path.slice(0, corte);
  };

  const criar = async (caminho: string, isDir: boolean) => {
    if (!project) return;
    try {
      await createEntry(project, caminho, isDir);
      bumpRevision();
      if (!isDir) openFile(caminho);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  const renomear = async (origem: string, destino: string) => {
    if (!project) return;
    try {
      await moveEntry(project, origem, destino);
      // Mesma razão de fecharAbasSob: sem remapear, a aba continuaria
      // apontando para o caminho antigo (que não existe mais no disco).
      for (const t of tabs) {
        if (t === origem) {
          closeTab(t);
          openFile(destino);
        } else if (t.startsWith(`${origem}/`)) {
          closeTab(t);
          openFile(`${destino}${t.slice(origem.length)}`);
        }
      }
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  // Fecha qualquer aba aberta para o próprio caminho excluído ou, no caso de
  // pasta, para qualquer arquivo que vivia dentro dela — sem isto a aba fica
  // "fantasma", apontando para um arquivo que não existe mais no disco (um
  // "Salvar" nela recriaria o arquivo do zero, sem avisar o usuário).
  const fecharAbasSob = (path: string) => {
    for (const t of tabs) {
      if (t === path || t.startsWith(`${path}/`)) closeTab(t);
    }
  };

  const excluir = async (entry: Entry) => {
    if (!project) return;
    try {
      await deleteEntry(project, entry.path, entry.is_dir);
      fecharAbasSob(entry.path);
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  const excluirLote = async (alvos: string[]) => {
    if (!project) return;
    // `recursive=true` incondicional é seguro aqui: para um arquivo o
    // backend simplesmente ignora a flag (fs.delete só usa `recursive`
    // quando o alvo é diretório).
    for (const path of alvos) {
      try {
        await deleteEntry(project, path, true);
        fecharAbasSob(path);
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
      }
    }
    setSelected(new Set());
    bumpRevision();
  };

  const iniciarDrag = (e: React.DragEvent, entry: Entry) => {
    const paths = selected.has(entry.path) && selected.size > 1 ? Array.from(selected) : [entry.path];
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("application/x-sicoobito-paths", JSON.stringify(paths));
  };

  const soltarEm = async (e: React.DragEvent, destFolder: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverPath(null);
    const raw = e.dataTransfer.getData("application/x-sicoobito-paths");
    if (!raw) return;
    let paths: string[];
    try {
      paths = JSON.parse(raw);
    } catch {
      return;
    }
    for (const origem of paths) {
      const nome = origem.split("/").pop();
      if (!nome) continue;
      const destino = destFolder ? `${destFolder}/${nome}` : nome;
      if (destino === origem || destFolder === origem) continue;
      await renomear(origem, destino);
    }
  };

  const renderar = (subpath: string, profundidade: number) => {
    const list = levels[subpath] ?? [];
    const filtered = filterText
      ? list.filter((e) => e.name.toLowerCase().includes(filterText.toLowerCase()) || e.is_dir)
      : list;

    return filtered.map((entry) => (
      <div key={entry.path} className="tree-node">
        <button
          type="button"
          data-path={entry.path}
          className={[
            "tree-row",
            active === entry.path && "active",
            selected.has(entry.path) && "selected",
            dragOverPath === entry.path && "drag-over",
          ]
            .filter(Boolean)
            .join(" ")}
          style={{ paddingLeft: 10 + profundidade * 14 }}
          onClick={(e) => alternar(entry, e)}
          onDoubleClick={() => {
            if (!entry.is_dir) pinTab(entry.path);
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            if (!selected.has(entry.path)) setSelected(new Set([entry.path]));
            setMenu({ x: e.clientX, y: e.clientY, entry });
          }}
          draggable
          onDragStart={(e) => iniciarDrag(e, entry)}
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setDragOverPath(entry.is_dir ? entry.path : pastaDe(entry));
          }}
          onDragLeave={() => setDragOverPath((p) => (p === entry.path ? null : p))}
          onDrop={(e) => void soltarEm(e, entry.is_dir ? entry.path : pastaDe(entry))}
          title={entry.path}
        >
          {entry.is_dir ? (
            <span className={`tree-chevron ${expanded.has(entry.path) ? "open" : ""}`}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
            </span>
          ) : (
            <span className="tree-chevron-space" />
          )}
          <FileIcon filename={entry.name} isFolder={entry.is_dir} isOpen={expanded.has(entry.path)} />
          <span className="tree-name">{entry.name}</span>
        </button>
        {entry.is_dir && expanded.has(entry.path) && renderar(entry.path, profundidade + 1)}
      </div>
    ));
  };

  return (
    <div
      className="panel-body"
      onContextMenu={(e) => {
        if (e.target === e.currentTarget) {
          e.preventDefault();
          setMenu({ x: e.clientX, y: e.clientY, entry: null });
        }
      }}
    >
      <div className="panel-header">
        <span className="panel-header-title">Explorer</span>
        <div className="panel-actions-bar">
          <button
            type="button"
            className="icon-action-btn"
            title="Novo Arquivo"
            onClick={() => setDialogo({ tipo: "novo-arquivo", base: "", inicial: "" })}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="11" x2="12" y2="17" />
              <line x1="9" y1="14" x2="15" y2="14" />
            </svg>
          </button>
          <button
            type="button"
            className="icon-action-btn"
            title="Nova Pasta"
            onClick={() => setDialogo({ tipo: "nova-pasta", base: "", inicial: "" })}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              <line x1="12" y1="11" x2="12" y2="17" />
              <line x1="9" y1="14" x2="15" y2="14" />
            </svg>
          </button>
          <button
            type="button"
            className="icon-action-btn"
            title="Colapsar Pastas"
            onClick={() => setExpanded(new Set())}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="4 14 10 14 10 20" />
              <polyline points="20 10 14 10 14 4" />
              <line x1="14" y1="10" x2="21" y2="3" />
              <line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          </button>
          <button
            type="button"
            className="icon-action-btn"
            title="Recarregar Árvore"
            onClick={() => bumpRevision()}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
        </div>
      </div>

      <div className="tree-quick-filter">
        <input
          type="text"
          placeholder="Filtrar arquivos..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          className="tree-filter-input"
        />
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      <div
        className={`tree${dragOverPath === "" ? " drag-over-root" : ""}`}
        ref={treeRef}
        onDragOver={(e) => {
          if (e.target !== e.currentTarget) return;
          e.preventDefault();
          setDragOverPath("");
        }}
        onDragLeave={(e) => {
          if (e.target === e.currentTarget) setDragOverPath((p) => (p === "" ? null : p));
        }}
        onDrop={(e) => {
          if (e.target !== e.currentTarget) return;
          void soltarEm(e, "");
        }}
      >
        {renderar(".", 0)}
      </div>

      <div className="explorer-subsections">
        <details className="explorer-collapsible" open>
          <summary className="explorer-collapsible-header">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="chevron-icon">
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span>Estrutura do Código</span>
          </summary>
          <div className="explorer-collapsible-content">
            {active ? (
              <div className="outline-item">
                <span className="outline-symbol">ƒ</span> {active.split("/").pop()}
              </div>
            ) : (
              <div className="outline-empty">Nenhum arquivo ativo para outline</div>
            )}
          </div>
        </details>

        <details className="explorer-collapsible">
          <summary className="explorer-collapsible-header">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="chevron-icon">
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span>Linha do Tempo</span>
          </summary>
          <div className="explorer-collapsible-content">
            <div className="timeline-item">
              <span className="timeline-dot" />
              <span className="timeline-label">Histórico Local / Git</span>
            </div>
          </div>
        </details>
      </div>

      {menu && (
        <>
          <div className="menu-backdrop" onClick={() => setMenu(null)} onContextMenu={(e) => { e.preventDefault(); setMenu(null); }} />
          <div className="context-menu" style={{ left: menu.x, top: menu.y }}>
            <button type="button" onClick={() => { setDialogo({ tipo: "novo-arquivo", base: pastaDe(menu.entry), inicial: "" }); setMenu(null); }}>
              📄 Novo Arquivo
            </button>
            <button type="button" onClick={() => { setDialogo({ tipo: "nova-pasta", base: pastaDe(menu.entry), inicial: "" }); setMenu(null); }}>
              📁 Nova Pasta
            </button>
            {menu.entry && selected.size > 1 && selected.has(menu.entry.path) ? (
              <button
                type="button"
                className="danger"
                onClick={() => {
                  setDialogo({ tipo: "excluir-lote", alvos: Array.from(selected) });
                  setMenu(null);
                }}
              >
                🗑️ Excluir {selected.size} itens selecionados
              </button>
            ) : menu.entry && (
              <>
                <button type="button" onClick={() => {
                  navigator.clipboard?.writeText(menu.entry!.path);
                  setMenu(null);
                }}>
                  📋 Copiar Caminho
                </button>
                <button type="button" onClick={() => { setDialogo({ tipo: "renomear", base: menu.entry!.path, inicial: menu.entry!.name }); setMenu(null); }}>
                  ✏️ Renomear
                </button>
                <button type="button" className="danger" onClick={() => { setDialogo({ tipo: "excluir", alvo: menu.entry! }); setMenu(null); }}>
                  🗑️ Excluir
                </button>
              </>
            )}
          </div>
        </>
      )}

      {dialogo?.tipo === "novo-arquivo" && (
        <PromptDialog
          title="Nome do novo arquivo"
          onConfirm={(nome) => void criar(dialogo.base ? `${dialogo.base}/${nome}` : nome, false)}
          onClose={() => setDialogo(null)}
        />
      )}
      {dialogo?.tipo === "nova-pasta" && (
        <PromptDialog
          title="Nome da nova pasta"
          onConfirm={(nome) => void criar(dialogo.base ? `${dialogo.base}/${nome}` : nome, true)}
          onClose={() => setDialogo(null)}
        />
      )}
      {dialogo?.tipo === "renomear" && (
        <PromptDialog
          title="Novo nome"
          initial={dialogo.inicial}
          onConfirm={(nome) => {
            const corte = dialogo.base.lastIndexOf("/");
            const pai = corte === -1 ? "" : dialogo.base.slice(0, corte);
            void renomear(dialogo.base, pai ? `${pai}/${nome}` : nome);
          }}
          onClose={() => setDialogo(null)}
        />
      )}
      {dialogo?.tipo === "excluir" && (
        <ConfirmDialog
          danger
          message={
            <>
              Excluir <code>{dialogo.alvo.path}</code>
              {dialogo.alvo.is_dir ? " e todo o seu conteúdo?" : "?"}
            </>
          }
          onConfirm={() => void excluir(dialogo.alvo)}
          onClose={() => setDialogo(null)}
        />
      )}
      {dialogo?.tipo === "excluir-lote" && (
        <ConfirmDialog
          danger
          message={`Excluir ${dialogo.alvos.length} itens selecionados? Pastas são removidas com todo o conteúdo.`}
          onConfirm={() => void excluirLote(dialogo.alvos)}
          onClose={() => setDialogo(null)}
        />
      )}
    </div>
  );
}

// ── Busca ───────────────────────────────────────────────────────────────────

interface Match {
  path: string;
  line: number;
  column: number;
  text: string;
  preview: string;
}

export function SearchPanel() {
  const { project, openFile, bumpRevision } = useIde();
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [showReplace, setShowReplace] = useState(false);
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [matches, setMatches] = useState<Match[]>([]);
  const [resumo, setResumo] = useState<string | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [confirmar, setConfirmar] = useState(false);

  const buscar = async () => {
    if (!project || !query.trim()) return;
    setBuscando(true);
    setErro(null);
    try {
      const data = await searchWorkspace(project, query, { regex, caseSensitive });
      setMatches(data.matches);
      setResumo(
        `${data.matches.length}${data.truncated ? "+" : ""} ocorrências em ` +
          `${data.files_with_matches} de ${data.files_searched} arquivos`,
      );
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
      setMatches([]);
    } finally {
      setBuscando(false);
    }
  };

  const substituir = async () => {
    if (!project || !query.trim()) return;
    try {
      const data = await replaceInWorkspace(project, query, replacement, {
        regex,
        caseSensitive,
      });
      setResumo(`${data.replacements} substituições em ${data.files_changed} arquivos`);
      setMatches([]);
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="panel-body search-panel-body">
      <div className="panel-header">
        <span className="panel-header-title">Busca & Substituição</span>
      </div>
      <div className="search-form">
        {/* Campo de Busca Principal */}
        <div className="search-field-row">
          <div className="search-input-container">
            <svg className="search-field-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              className="search-field-input"
              value={query}
              placeholder="Localizar no código..."
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void buscar()}
            />
            <div className="search-field-options">
              <button
                type="button"
                className={`search-opt-btn ${caseSensitive ? "active" : ""}`}
                onClick={() => setCaseSensitive(!caseSensitive)}
                title="Diferenciar maiúsculas/minúsculas (Aa)"
              >
                Aa
              </button>
              <button
                type="button"
                className={`search-opt-btn ${regex ? "active" : ""}`}
                onClick={() => setRegex(!regex)}
                title="Usar Expressão Regular (.*)"
              >
                .*
              </button>
            </div>
          </div>
          <button
            type="button"
            className={`search-toggle-btn ${showReplace ? "active" : ""}`}
            onClick={() => setShowReplace(!showReplace)}
            title="Alternar campo de Substituir"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="7 10 12 15 17 10" />
              <polyline points="7 14 12 9 17 14" />
            </svg>
          </button>
        </div>

        {/* Campo de Substituição */}
        {showReplace && (
          <div className="search-field-row">
            <div className="search-input-container">
              <svg className="search-field-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="17 1 21 5 17 9" />
                <path d="M3 11V9a4 4 0 0 1 4-4h14" />
              </svg>
              <input
                type="text"
                className="search-field-input"
                value={replacement}
                placeholder="Substituir por..."
                onChange={(e) => setReplacement(e.target.value)}
              />
            </div>
          </div>
        )}

        {/* Botões de Ação */}
        <div className="search-action-row">
          <button
            type="button"
            className="search-btn-primary"
            onClick={() => void buscar()}
            disabled={buscando || !query.trim()}
          >
            {buscando ? "Buscando..." : "Localizar"}
          </button>
          {showReplace && (
            <button
              type="button"
              className="search-btn-danger"
              onClick={() => setConfirmar(true)}
              disabled={!query.trim() || matches.length === 0}
            >
              Substituir Tudo
            </button>
          )}
        </div>
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      {resumo && <div className="search-summary">{resumo}</div>}

      {/* Lista de Resultados Encontrados */}
      <div className="search-results-list">
        {matches.map((m, i) => {
          const filename = m.path.split("/").pop() ?? m.path;
          const dir = m.path.includes("/") ? m.path.substring(0, m.path.lastIndexOf("/")) : "";
          return (
            <button
              key={`${m.path}:${m.line}:${m.column}:${i}`}
              type="button"
              className="search-match-card"
              onClick={() => openFile(m.path, { line: m.line, column: m.column })}
            >
              <div className="search-match-header">
                <span className="search-match-filename">{filename}</span>
                <span className="search-match-pos">:{m.line}:{m.column}</span>
                {dir && <span className="search-match-dir">{dir}</span>}
              </div>
              <div className="search-match-preview">{m.preview || m.text}</div>
            </button>
          );
        })}
      </div>

      {confirmar && (
        <ConfirmDialog
          danger
          message={
            <>
              Substituir <code>{query}</code> por <code>{replacement || "(vazio)"}</code> em todo o
              projeto? Isto altera arquivos no disco e não tem desfazer.
            </>
          }
          onConfirm={() => void substituir()}
          onClose={() => setConfirmar(false)}
        />
      )}
    </div>
  );
}

// ── Git ─────────────────────────────────────────────────────────────────────

export function GitPanel() {
  const { project, openFile, revision, bumpRevision, reloadProjects } = useIde();
  const [estado, setEstado] = useState<{ branch: string; dirty: boolean; files: GitFile[] } | null>(null);
  const [branches, setBranches] = useState<string[]>([]);
  const [mensagem, setMensagem] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [novoBranch, setNovoBranch] = useState(false);

  const recarregar = useCallback(async () => {
    if (!project) return;
    try {
      const [st, br] = await Promise.all([getGitStatus(project), getGitBranches(project)]);
      setEstado(st);
      setBranches(br);
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
      setEstado(null);
    }
  }, [project]);

  useEffect(() => { void recarregar(); }, [recarregar, revision]);

  const acao = async (fn: () => Promise<unknown>, sucesso?: string) => {
    try {
      await fn();
      setErro(null);
      if (sucesso) setAviso(sucesso);
      await recarregar();
      void reloadProjects();
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  if (!project) return <div className="tree-hint">Selecione um projeto.</div>;

  const stagedFiles = estado?.files.filter((f) => f.status === "staged") ?? [];
  const unstagedFiles = estado?.files.filter((f) => f.status !== "staged") ?? [];

  return (
    <div className="panel-body">
      <div className="panel-header">
        <span className="panel-header-title">Controle Git</span>
      </div>
      {erro && <div className="panel-error">{erro}</div>}
      {aviso && <div className="tree-hint">{aviso}</div>}

      {estado && (
        <>
          <div className="git-header-bar">
            <div className="git-branch-wrapper">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="6" y1="3" x2="6" y2="15" />
                <circle cx="18" cy="6" r="3" />
                <circle cx="6" cy="18" r="3" />
                <path d="M18 9a9 9 0 0 1-9 9" />
              </svg>
              <select
                className="git-branch-select"
                value={estado.branch}
                onChange={(e) => void acao(() => checkoutBranch(project, e.target.value))}
                title="Alternar branch atual"
              >
                {branches.map((b) => <option key={b} value={b}>{b}</option>)}
                {!branches.includes(estado.branch) && <option value={estado.branch}>{estado.branch}</option>}
              </select>
              <button
                type="button"
                onClick={() => setNovoBranch(true)}
                title="Criar novo branch"
                className="git-icon-btn"
              >
                +
              </button>
            </div>
          </div>

          <div className="git-files-container">
            {stagedFiles.length > 0 && (
              <div className="git-group">
                <div className="git-group-title">
                  <span>Preparadas ({stagedFiles.length})</span>
                  <button
                    type="button"
                    className="git-action-sm"
                    title="Despreparar todas (Unstage All)"
                    onClick={() => void acao(() => unstageFiles(project, stagedFiles.map((f) => f.path)))}
                  >
                    −
                  </button>
                </div>
                {stagedFiles.map((f) => {
                  const filename = f.path.split("/").pop() ?? f.path;
                  const dir = f.path.includes("/") ? f.path.substring(0, f.path.lastIndexOf("/")) : "";
                  return (
                    <div key={`staged:${f.path}`} className="git-file-row">
                      <span className="git-badge git-status-staged" title="Alteração preparada (Staged)">S</span>
                      <button type="button" className="git-file-info" onClick={() => openFile(f.path)} title={f.path}>
                        <span className="git-file-name">{filename}</span>
                        {dir && <span className="git-file-dir">{dir}</span>}
                      </button>
                      <button
                        type="button"
                        className="git-action-sm"
                        title="Despreparar arquivo (Unstage)"
                        onClick={() => void acao(() => unstageFiles(project, [f.path]))}
                      >
                        −
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="git-group">
              <div className="git-group-title">
                <span>Alterações ({unstagedFiles.length})</span>
                {unstagedFiles.length > 0 && (
                  <button
                    type="button"
                    className="git-action-sm"
                    title="Preparar todas (Stage All)"
                    onClick={() => void acao(() => stageFiles(project, unstagedFiles.map((f) => f.path)))}
                  >
                    +
                  </button>
                )}
              </div>
              {unstagedFiles.length === 0 && stagedFiles.length === 0 && (
                <div className="tree-hint">Nenhuma alteração pendente. Árvore limpa.</div>
              )}
              {unstagedFiles.map((f) => {
                const filename = f.path.split("/").pop() ?? f.path;
                const dir = f.path.includes("/") ? f.path.substring(0, f.path.lastIndexOf("/")) : "";
                const stLower = f.status.toLowerCase();
                const badgeText = stLower === "modified" ? "M" : stLower === "untracked" ? "U" : stLower === "deleted" ? "D" : "A";
                return (
                  <div key={`unstaged:${f.path}`} className="git-file-row">
                    <span className={`git-badge git-status-${stLower}`} title={`Status: ${f.status}`}>
                      {badgeText}
                    </span>
                    <button type="button" className="git-file-info" onClick={() => openFile(f.path)} title={f.path}>
                      <span className="git-file-name">{filename}</span>
                      {dir && <span className="git-file-dir">{dir}</span>}
                    </button>
                    <button
                      type="button"
                      className="git-action-sm"
                      title="Preparar arquivo (Stage)"
                      onClick={() => void acao(() => stageFiles(project, [f.path]))}
                    >
                      +
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="git-commit">
            <textarea
              className="git-commit-textarea"
              value={mensagem}
              placeholder="Mensagem de commit (ex: feat: refatora layout do git)"
              rows={3}
              onChange={(e) => setMensagem(e.target.value)}
            />
            <button
              type="button"
              className="primary git-commit-btn"
              disabled={!mensagem.trim() || !estado.dirty}
              onClick={() =>
                void acao(async () => {
                  if (stagedFiles.length === 0 && unstagedFiles.length > 0) {
                    await stageFiles(project, unstagedFiles.map((f) => f.path));
                  }
                  await commitChanges(project, mensagem);
                  setMensagem("");
                }, "Commit realizado com sucesso!")
              }
            >
              ✓ Commit & Sync
            </button>
          </div>
        </>
      )}

      {novoBranch && (
        <PromptDialog
          title="Nome do novo branch"
          confirmLabel="Criar Branch"
          onConfirm={(nome) => void acao(() => checkoutBranch(project, nome, true))}
          onClose={() => setNovoBranch(false)}
        />
      )}
    </div>
  );
}

// ── Debugger ────────────────────────────────────────────────────────────────

export function DebugPanel() {
  const { project, active, setTerminalOpen } = useIde();
  const [argsInput, setArgsInput] = useState("");

  if (!project) return <div className="tree-hint">Selecione um projeto.</div>;

  const getRunCommand = (file: string | null, debugMode: boolean = false) => {
    if (!file) return "python -m pytest";
    const lower = file.toLowerCase();
    const args = argsInput.trim() ? ` ${argsInput.trim()}` : "";
    if (lower.endsWith(".py")) {
      return debugMode ? `python -m pdb ${file}${args}` : `python ${file}${args}`;
    }
    if (lower.endsWith(".js") || lower.endsWith(".ts") || lower.endsWith(".tsx")) {
      return debugMode ? `node --inspect ${file}${args}` : `node ${file}${args}`;
    }
    if (lower.endsWith(".go")) {
      return `go run ${file}${args}`;
    }
    if (lower.endsWith(".sh") || lower.endsWith(".bash")) {
      return `bash ${file}${args}`;
    }
    return `./${file}${args}`;
  };

  const executeCommandInTerminal = (cmd: string) => {
    setTerminalOpen(true);
    // Dispara via evento global para o terminal capturar e rodar
    const evt = new CustomEvent("sicoobito:terminal:exec", { detail: { command: cmd } });
    window.dispatchEvent(evt);
  };

  return (
    <div className="panel-body" style={{ padding: "0 0 10px 0", display: "flex", flexDirection: "column" }}>
      <div className="panel-header">
        <span className="panel-header-title">Executar & Debugar</span>
      </div>
      <div style={{ padding: "10px", gap: "10px", display: "flex", flexDirection: "column" }}>
      <div style={{ background: "var(--surface-2)", padding: "8px 10px", borderRadius: "5px", border: "1px solid var(--border)" }}>
        <div style={{ fontSize: "10px", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "2px" }}>
          Arquivo em Execução
        </div>
        <div style={{ fontWeight: 600, color: "#4ade80", fontFamily: "var(--font-mono)", fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={active ?? ""}>
          {active ? active.split("/").pop() : "(nenhum arquivo aberto)"}
        </div>
        {active && active.includes("/") && (
          <div style={{ fontSize: "10px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {active}
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        <button
          type="button"
          className="primary"
          style={{ padding: "6px 10px", fontSize: "11.5px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", background: "#16a34a", border: "none", borderRadius: "4px", fontWeight: 500 }}
          onClick={() => executeCommandInTerminal(getRunCommand(active, false))}
          disabled={!active}
        >
          ▶ Executar Arquivo Ativo
        </button>

        <button
          type="button"
          className="theme-btn"
          style={{ padding: "6px 10px", fontSize: "11.5px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", background: "#7c3aed", color: "#fff", border: "none", borderRadius: "4px", fontWeight: 500 }}
          onClick={() => executeCommandInTerminal(getRunCommand(active, true))}
          disabled={!active}
        >
          🐞 Depurar (PDB / Inspect)
        </button>

        <button
          type="button"
          className="theme-btn"
          style={{ padding: "5px 10px", fontSize: "11px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", borderRadius: "4px" }}
          onClick={() => executeCommandInTerminal("python -m pytest")}
        >
          🧪 Rodar Testes (pytest)
        </button>
      </div>

      <div style={{ marginTop: "4px" }}>
        <label style={{ fontSize: "10.5px", color: "#94a3b8", display: "block", marginBottom: "3px" }}>
          Argumentos adicionais:
        </label>
        <input
          type="text"
          value={argsInput}
          onChange={(e) => setArgsInput(e.target.value)}
          placeholder="ex: --verbose arg1"
          style={{ width: "100%", padding: "4px 8px", borderRadius: "4px", background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)", fontSize: "11px" }}
        />
      </div>

      <div style={{ marginTop: "auto", fontSize: "10.5px", color: "var(--text-muted)", background: "rgba(255,255,255,0.02)", border: "1px solid var(--border)", padding: "6px 8px", borderRadius: "4px", lineHeight: "1.4" }}>
        💡 Saída stdout/stderr exibida em tempo real no terminal do sandbox abaixo.
      </div>
      </div>
    </div>
  );
}

// ── Navegador ───────────────────────────────────────────────────────────────

/** Um id de sessão por painel aberto — o serviço `browser` reaproveita a
 * mesma página (cookies, formulário preenchido) entre uma ação e a próxima,
 * então precisa ser estável durante a vida do painel, não gerado a cada ação. */
function useStablePanelSessionId(): string {
  const ref = useRef<string>("");
  if (!ref.current) {
    ref.current =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
  return ref.current;
}

export function BrowserPanel() {
  const sessionId = useStablePanelSessionId();
  const [urlInput, setUrlInput] = useState("http://web:5400");
  const [currentUrl, setCurrentUrl] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const capturar = useCallback(async () => {
    try {
      const shot = await browserAction({ sessionId, action: "screenshot" });
      setImage(shot.image_base64 ?? null);
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  }, [sessionId]);

  const navegar = useCallback(
    async (destino: string) => {
      const bruto = destino.trim();
      if (!bruto) return;
      const alvo = /^https?:\/\//i.test(bruto) ? bruto : `https://${bruto}`;
      setLoading(true);
      setErro(null);
      setContent(null);
      try {
        const resultado = await browserAction({ sessionId, action: "navigate", url: alvo });
        setCurrentUrl(resultado.url ?? alvo);
        setTitle(resultado.title ?? null);
        setUrlInput(resultado.url ?? alvo);
        await capturar();
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [sessionId, capturar],
  );

  // Clicar na captura navega o navegador de verdade para aquele ponto, na
  // escala real da página (a imagem exibida pode estar redimensionada pelo
  // CSS) — depois recaptura para o usuário ver o efeito do clique.
  const clicarNaCaptura = useCallback(
    async (e: React.MouseEvent<HTMLImageElement>) => {
      if (!currentUrl || !imgRef.current || loading) return;
      const img = imgRef.current;
      const rect = img.getBoundingClientRect();
      const x = (e.clientX - rect.left) * (img.naturalWidth / rect.width);
      const y = (e.clientY - rect.top) * (img.naturalHeight / rect.height);
      setLoading(true);
      setErro(null);
      try {
        await browserAction({ sessionId, action: "click", x, y });
        await capturar();
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [sessionId, currentUrl, loading, capturar],
  );

  const verConteudo = useCallback(async () => {
    setErro(null);
    try {
      const resultado = await browserAction({ sessionId, action: "content" });
      setContent(resultado.text ?? "");
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  }, [sessionId]);

  const reiniciar = useCallback(async () => {
    try {
      await closeBrowserSession(sessionId);
    } catch {
      // Sessão pode já não existir do lado do serviço — sem problema, o
      // ponto é garantir que a próxima navegação comece de uma página vazia.
    }
    setImage(null);
    setContent(null);
    setCurrentUrl(null);
    setTitle(null);
    setErro(null);
  }, [sessionId]);

  // Fecha a página do Chromium ao desmontar o painel (troca de projeto,
  // fechar aba) — sem isso a sessão fica presa até o TTL do serviço expirar.
  useEffect(() => {
    return () => {
      void closeBrowserSession(sessionId).catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="panel-body">
      <div className="panel-header">
        <span className="panel-header-title">Navegador</span>
        <div className="panel-actions-bar">
          <button
            type="button"
            className="icon-action-btn"
            title="Tirar novo screenshot"
            onClick={() => void capturar()}
            disabled={!currentUrl || loading}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
          <button
            type="button"
            className="icon-action-btn"
            title="Fechar sessão do navegador (recomeçar do zero)"
            onClick={() => void reiniciar()}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="browser-panel-toolbar">
        <input
          type="text"
          className="browser-panel-url-input"
          value={urlInput}
          placeholder="http://web:5400 ou https://exemplo.com"
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void navegar(urlInput)}
        />
        <button
          type="button"
          className="primary browser-panel-go-btn"
          onClick={() => void navegar(urlInput)}
          disabled={loading || !urlInput.trim()}
        >
          {loading ? "…" : "Ir"}
        </button>
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      {title && (
        <div className="browser-panel-status" title={currentUrl ?? undefined}>
          {title} — {currentUrl}
        </div>
      )}

      <div className="browser-panel-viewport">
        {image ? (
          <img
            ref={imgRef}
            src={`data:image/png;base64,${image}`}
            alt={title || currentUrl || "captura da página"}
            onClick={(e) => void clicarNaCaptura(e)}
            title="Clique para interagir com a página nesse ponto"
          />
        ) : (
          <div className="tree-hint">
            Digite uma URL acima e pressione &quot;Ir&quot; para abrir uma página num navegador de
            verdade — o serviço é isolado numa rede própria que só alcança{" "}
            <code>web</code>/<code>api</code>, nunca a internet pública.
          </div>
        )}
      </div>

      <div className="explorer-subsections">
        <details className="explorer-collapsible">
          <summary className="explorer-collapsible-header">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="chevron-icon">
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span>Texto visível da página</span>
          </summary>
          <div className="explorer-collapsible-content">
            <button
              type="button"
              className="theme-btn"
              style={{ marginBottom: 6 }}
              onClick={() => void verConteudo()}
              disabled={!currentUrl}
            >
              Ler texto da página
            </button>
          </div>
        </details>
      </div>
    </div>
  );
}

// ── PackagesPanel ───────────────────────────────────────────────────────────

export function PackagesPanel() {
  const { project, openFile } = useIde();
  const [packages, setPackages] = useState<PackageItem[]>([]);
  const [reqMap, setReqMap] = useState<Record<string, string>>({});
  const [reqExists, setReqExists] = useState(false);
  const [venvExists, setVenvExists] = useState(false);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [inputPkg, setInputPkg] = useState("");
  const [filterText, setFilterText] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [msgSuccess, setMsgSuccess] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    setErro(null);
    try {
      const data = await getProjectPackages(project);
      setPackages(data.packages);
      setReqMap(data.requirements_map);
      setReqExists(data.requirements_exists);
      setVenvExists(data.venv_exists);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [project]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const handleInstall = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!project || !inputPkg.trim() || actionLoading) return;

    const target = inputPkg.trim();
    setActionLoading(`Instalando ${target}...`);
    setErro(null);
    setMsgSuccess(null);
    try {
      const res = await installProjectPackage(project, target, true);
      setInputPkg("");
      setMsgSuccess(`Pacote '${res.package}' (${res.version ?? "OK"}) instalado e gravado no requirements.txt!`);
      await carregar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  };

  const handleUninstall = async (pkgName: string) => {
    if (!project || actionLoading) return;
    if (!window.confirm(`Desinstalar o pacote '${pkgName}' do ambiente do projeto?`)) return;

    setActionLoading(`Desinstalando ${pkgName}...`);
    setErro(null);
    setMsgSuccess(null);
    try {
      await uninstallProjectPackage(project, pkgName, true);
      setMsgSuccess(`Pacote '${pkgName}' removido e atualizado no requirements.txt!`);
      await carregar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  };

  const handleSync = async () => {
    if (!project || actionLoading) return;
    setActionLoading("Sincronizando de requirements.txt...");
    setErro(null);
    setMsgSuccess(null);
    try {
      await syncProjectRequirements(project);
      setMsgSuccess("Ambiente sincronizado com sucesso com o requirements.txt!");
      await carregar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  };

  const filtrados = packages.filter(
    (p) =>
      p.name.toLowerCase().includes(filterText.toLowerCase()) ||
      p.version.toLowerCase().includes(filterText.toLowerCase())
  );

  return (
    <div className="panel-body packages-panel-body">
      <div className="panel-header">
        <div className="panel-header-title-group">
          <span className="panel-header-title">📦 Pacotes do Projeto</span>
          <span className="packages-count-badge">{packages.length}</span>
        </div>
        <div className="panel-actions-bar">
          <button
            type="button"
            className="icon-action-btn"
            title="Recarregar pacotes"
            onClick={() => void carregar()}
            disabled={loading}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.5 2v6h-6M2.5 22v-6h6" />
              <path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8M22 12.5a10 10 0 0 1-18.8 4.2L2.5 16" />
            </svg>
          </button>
          <button
            type="button"
            className="icon-action-btn"
            title="Abrir requirements.txt no editor"
            onClick={() => openFile("requirements.txt")}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          </button>
        </div>
      </div>

      <div className="packages-section-install">
        <form onSubmit={handleInstall} className="packages-form-row">
          <input
            type="text"
            className="packages-input"
            placeholder="Nome do pacote (ex: pytest)..."
            value={inputPkg}
            onChange={(e) => setInputPkg(e.target.value)}
            disabled={!!actionLoading}
          />
          <button
            type="submit"
            className="packages-btn-primary"
            disabled={!inputPkg.trim() || !!actionLoading}
          >
            {actionLoading ? "…" : "Instalar"}
          </button>
        </form>

        <div className="packages-sub-actions">
          <div className="packages-sync-info">
            <span>⚡ Auto-sync com <code>requirements.txt</code></span>
          </div>
          <button
            type="button"
            onClick={() => void handleSync()}
            disabled={!!actionLoading || !reqExists}
            className="packages-btn-sync"
            title="Instalar dependências do requirements.txt"
          >
            🔄 Sincronizar Tudo
          </button>
        </div>
      </div>

      {actionLoading && (
        <div className="packages-status-loading">
          <span className="spin-icon">⏳</span>
          <span>{actionLoading}</span>
        </div>
      )}

      {erro && <div className="panel-error">{erro}</div>}
      {msgSuccess && <div className="packages-status-success">{msgSuccess}</div>}

      <div className="packages-filter-box">
        <input
          type="text"
          className="packages-input-filter"
          placeholder="Filtrar pacotes instalados..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
      </div>

      <div className="packages-list-scroll">
        {loading ? (
          <div className="packages-empty-state">Carregando ambiente virtual do projeto...</div>
        ) : filtrados.length === 0 ? (
          <div className="packages-empty-state">
            {packages.length === 0
              ? "Nenhum pacote instalado no .venv do projeto ainda. Digite o nome do pacote acima para instalar!"
              : "Nenhum pacote encontrado com este filtro."}
          </div>
        ) : (
          <div className="packages-items-grid">
            {filtrados.map((pkg) => {
              const normName = pkg.name.toLowerCase().replace("_", "-");
              const inReq = reqMap[normName] !== undefined;
              return (
                <div key={pkg.name} className="package-item-card">
                  <div className="package-item-info">
                    <div className="package-item-title-row">
                      <span className="package-item-name">{pkg.name}</span>
                      {inReq && <span className="package-req-tag">req.txt</span>}
                    </div>
                    <span className="package-item-version">v{pkg.version}</span>
                  </div>
                  <button
                    type="button"
                    className="icon-action-btn danger"
                    title={`Desinstalar ${pkg.name}`}
                    onClick={() => void handleUninstall(pkg.name)}
                    disabled={!!actionLoading}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="packages-footer">
        <span className={`status-dot ${venvExists ? "active" : ""}`} />
        <span>
          {venvExists
            ? "Ambiente .venv ativado e persistente no projeto"
            : "O .venv será criado automaticamente na 1ª instalação"}
        </span>
      </div>
    </div>
  );
}

// ── Extensions (Extensões & Suporte a Linguagens) ──────────────────────────

export interface ExtensionItem {
  id: string;
  name: string;
  publisher: string;
  version: string;
  description: string;
  category: "LSP & Python" | "Node & Next.js" | "Frontend & Frameworks" | "C/C++ & Go" | "Containers & DevOps" | "IA & Agente" | "Outros";
  installed: boolean;
  active: boolean;
  latency_ms?: number;
  icon: string;
  downloads?: string;
  rating?: number;
  isRecommended?: boolean;
}

const EXTENSIONS_CATALOG: ExtensionItem[] = [
  {
    id: "meta.pyrefly",
    name: "Pyrefly - Python Language Server",
    publisher: "meta",
    version: "0.1.0",
    description: "Python autocomplete, typechecking & high-performance static analysis by Meta.",
    category: "LSP & Python",
    installed: true,
    active: true,
    latency_ms: 496,
    icon: "🦟",
  },
  {
    id: "ms-python.python",
    name: "Python",
    publisher: "ms-python",
    version: "2026.1.0",
    description: "Python language support with extension hooks, code formatting, linting & refactoring.",
    category: "LSP & Python",
    installed: true,
    active: true,
    latency_ms: 7072,
    icon: "🐍",
  },
  {
    id: "ms-python.debugpy",
    name: "Python Debugger",
    publisher: "ms-python",
    version: "2026.1.0",
    description: "Python Debugger extension using debugpy & Sicoobito container executor.",
    category: "LSP & Python",
    installed: true,
    active: true,
    latency_ms: 593,
    icon: "🐞",
  },
  {
    id: "ms-python.python-environments",
    name: "Python Environments",
    publisher: "ms-python",
    version: "2026.1.0",
    description: "Provides a unified python environment discovery and virtualenv manager.",
    category: "LSP & Python",
    installed: true,
    active: true,
    latency_ms: 874,
    icon: "📦",
  },
  {
    id: "ms-vscode.node-js",
    name: "Node.js & npm Package Manager",
    publisher: "ms-vscode",
    version: "2026.2.0",
    description: "Node.js environment discovery, package.json management & npm script execution.",
    category: "Node & Next.js",
    installed: true,
    active: true,
    latency_ms: 310,
    icon: "🟢",
  },
  {
    id: "vercel.nextjs-tools",
    name: "Next.js & React App Router",
    publisher: "vercel",
    version: "15.1.0",
    description: "Next.js App Router autocomplete, Server Components, Server Actions & route navigation.",
    category: "Node & Next.js",
    installed: true,
    active: true,
    latency_ms: 280,
    icon: "▲",
  },
  {
    id: "meta.react-devtools",
    name: "React 19 & JSX Features",
    publisher: "meta",
    version: "19.0.0",
    description: "React Hooks, Server Components, JSX/TSX autocomplete & component inspector.",
    category: "Frontend & Frameworks",
    installed: true,
    active: true,
    latency_ms: 210,
    icon: "⚛️",
  },
  {
    id: "vue.volar",
    name: "Vue.js Language Features (Volar)",
    publisher: "vue",
    version: "2.2.0",
    description: "Vue 3 Composition API, Single File Components (.vue), template typechecking & Volar LSP.",
    category: "Frontend & Frameworks",
    installed: true,
    active: true,
    latency_ms: 290,
    icon: "💚",
  },
  {
    id: "angular.ng-template",
    name: "Angular Language Service",
    publisher: "angular",
    version: "18.2.0",
    description: "Angular template IntelliSense, AOT typechecking & component navigation.",
    category: "Frontend & Frameworks",
    installed: true,
    active: true,
    latency_ms: 340,
    icon: "🅰️",
  },
  {
    id: "svelte.svelte-vscode",
    name: "Svelte & SvelteKit",
    publisher: "svelte",
    version: "108.4.0",
    description: "Svelte 5 Runes, SvelteKit routing, reactive state autocomplete & Svelte LSP.",
    category: "Frontend & Frameworks",
    installed: true,
    active: true,
    latency_ms: 250,
    icon: "🟧",
  },
  {
    id: "tailwindcss.vscode-tailwindcss",
    name: "Tailwind CSS IntelliSense",
    publisher: "tailwindcss",
    version: "0.14.0",
    description: "Advanced class autocomplete, CSS directive linting, variant preview & color picker.",
    category: "Frontend & Frameworks",
    installed: true,
    active: true,
    latency_ms: 180,
    icon: "🎨",
  },
  {
    id: "dbaeumer.vscode-eslint",
    name: "ESLint & Prettier",
    publisher: "dbaeumer",
    version: "3.0.10",
    description: "Real-time JavaScript/TypeScript linting, code formatting & style enforcement.",
    category: "Node & Next.js",
    installed: true,
    active: true,
    latency_ms: 190,
    icon: "✨",
  },
  {
    id: "Shopify.ruby-lsp",
    name: "Ruby LSP",
    publisher: "Shopify",
    version: "0.8.1",
    description: "VS Code plugin for connecting with Ruby LSP language server powered by Shopify.",
    category: "Outros",
    installed: true,
    active: true,
    latency_ms: 240,
    icon: "💎",
  },
  {
    id: "llvm-vs-code-extensions.clangd",
    name: "clangd",
    publisher: "llvm-vs-code-extensions",
    version: "0.1.30",
    description: "C/C++ completion, navigation, and static analysis powered by LLVM clangd engine.",
    category: "C/C++ & Go",
    installed: true,
    active: true,
    latency_ms: 380,
    icon: "🅲",
  },
  {
    id: "golang.go",
    name: "Go",
    publisher: "golang",
    version: "0.41.0",
    description: "Rich Go language support for Visual Studio Code using gopls LSP engine.",
    category: "C/C++ & Go",
    installed: true,
    active: true,
    latency_ms: 290,
    icon: "🅶",
  },
  {
    id: "ms-azuretools.container-tools",
    name: "Container Tools",
    publisher: "ms-azuretools",
    version: "1.28.0",
    description: "Makes it easy to create, manage, and debug containerized applications.",
    category: "Containers & DevOps",
    installed: true,
    active: true,
    latency_ms: 410,
    icon: "🧊",
  },
  {
    id: "ms-azuretools.docker",
    name: "Docker",
    publisher: "ms-azuretools",
    version: "1.29.0",
    description: "Makes it easy to create, manage, and debug Docker applications and Compose stacks.",
    category: "Containers & DevOps",
    installed: true,
    active: true,
    latency_ms: 360,
    icon: "🐳",
  },
  {
    id: "DavidAnson.markdownlint",
    name: "markdownlint",
    publisher: "DavidAnson",
    version: "0.57.0",
    description: "Markdown linting and style checking for repository documentation.",
    category: "Outros",
    installed: false,
    active: false,
    downloads: "1.5M",
    rating: 5,
    isRecommended: true,
    icon: "📝",
  },
  {
    id: "sicoobito.agentic-engine",
    name: "Sicoobito Agentic AI Engine",
    publisher: "sicoobito",
    version: "1.0.0",
    description: "Agente autônomo com suporte a múltiplos arquivos, RAG, terminal e auto-correção.",
    category: "IA & Agente",
    installed: true,
    active: true,
    latency_ms: 120,
    icon: "🤖",
  },
];

export function ExtensionsPanel() {
  const { bumpRevision } = useIde();
  const [filterText, setFilterText] = useState("");
  const [category, setCategory] = useState<"Todas" | "LSP & Python" | "Node & Next.js" | "Frontend & Frameworks" | "C/C++ & Go" | "Containers & DevOps" | "Recomendados">("Todas");
  const [activeEngine, setActiveEngine] = useState<"pyrefly" | "pyright">("pyrefly");
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>({
    "meta.pyrefly": true,
    "ms-python.python": true,
    "ms-python.debugpy": true,
    "ms-python.python-environments": true,
    "ms-vscode.node-js": true,
    "vercel.nextjs-tools": true,
    "meta.react-devtools": true,
    "vue.volar": true,
    "angular.ng-template": true,
    "svelte.svelte-vscode": true,
    "tailwindcss.vscode-tailwindcss": true,
    "dbaeumer.vscode-eslint": true,
    "Shopify.ruby-lsp": true,
    "llvm-vs-code-extensions.clangd": true,
    "golang.go": true,
    "ms-azuretools.container-tools": true,
    "ms-azuretools.docker": true,
    "DavidAnson.markdownlint": false,
    "sicoobito.agentic-engine": true,
  });
  const [selectedExt, setSelectedExt] = useState<ExtensionItem | null>(null);

  const toggleExt = (id: string) => {
    setEnabledMap((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const instalados = EXTENSIONS_CATALOG.filter((ext) => {
    if (category === "Recomendados") return false;
    const matchCat = category === "Todas" || ext.category === category;
    const matchText =
      !filterText.trim() ||
      ext.name.toLowerCase().includes(filterText.toLowerCase()) ||
      ext.publisher.toLowerCase().includes(filterText.toLowerCase()) ||
      ext.description.toLowerCase().includes(filterText.toLowerCase());
    return matchCat && matchText && ext.installed !== false;
  });

  const recomendados = EXTENSIONS_CATALOG.filter((ext) => {
    const matchText =
      !filterText.trim() ||
      ext.name.toLowerCase().includes(filterText.toLowerCase()) ||
      ext.publisher.toLowerCase().includes(filterText.toLowerCase()) ||
      ext.description.toLowerCase().includes(filterText.toLowerCase());
    return ext.isRecommended && matchText;
  });

  return (
    <div className="extensions-panel">
      <div className="extensions-header">
        <div className="extensions-title-group">
          <div className="extensions-title-icon">🧩</div>
          <div>
            <h3 className="extensions-title">Extensões & Linguagens</h3>
            <p className="extensions-subtitle">React, Vue, Angular, Svelte, Tailwind, Python & Node</p>
          </div>
        </div>
        <button
          type="button"
          className="icon-action-btn"
          title="Recarregar status de extensão"
          onClick={() => bumpRevision()}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21.5 2v6h-6M2.5 22v-6h6" />
            <path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8M22 12.5a10 10 0 0 1-18.8 4.2L2.5 16" />
          </svg>
        </button>
      </div>

      {/* Engine Selection Card for Python */}
      <div className="extensions-lsp-selector">
        <div className="lsp-selector-label">
          <span>Engine LSP Python Principal:</span>
          <span className="lsp-active-badge">{activeEngine === "pyrefly" ? "Meta Pyrefly" : "Pyright"}</span>
        </div>
        <div className="lsp-selector-buttons">
          <button
            type="button"
            className={`lsp-engine-btn ${activeEngine === "pyrefly" ? "active" : ""}`}
            onClick={() => setActiveEngine("pyrefly")}
          >
            🦟 Pyrefly (Meta)
          </button>
          <button
            type="button"
            className={`lsp-engine-btn ${activeEngine === "pyright" ? "active" : ""}`}
            onClick={() => setActiveEngine("pyright")}
          >
            🐍 Pyright (MS)
          </button>
        </div>
      </div>

      {/* Categories & Search */}
      <div className="extensions-search-box">
        <input
          type="text"
          className="extensions-input-search"
          placeholder="Buscar extensão, LSP, autor..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
      </div>

      <div className="extensions-categories">
        {(["Todas", "LSP & Python", "Node & Next.js", "Frontend & Frameworks", "C/C++ & Go", "Containers & DevOps", "Recomendados"] as const).map((cat) => (
          <button
            key={cat}
            type="button"
            className={`ext-cat-chip ${category === cat ? "active" : ""}`}
            onClick={() => setCategory(cat)}
          >
            {cat}
          </button>
        ))}
      </div>




      {/* Extension Items Grid */}
      <div className="extensions-scroll-list">
        {category !== "Recomendados" && (
          <>
            <div className="ext-section-header">
              <span>INSTALADOS</span>
              <span className="ext-section-count">{instalados.length}</span>
            </div>
            {instalados.map((ext) => {
              const isEnabled = enabledMap[ext.id] ?? true;
              return (
                <div key={ext.id} className={`ext-card ${!isEnabled ? "disabled" : ""}`}>
                  <div className="ext-card-header">
                    <span className="ext-card-icon">{ext.icon}</span>
                    <div className="ext-card-titles">
                      <div className="ext-card-name-row">
                        <span className="ext-card-name">{ext.name}</span>
                        {ext.latency_ms && (
                          <span className="ext-card-latency" title="Tempo de inicialização / latência LSP">
                            ⏱️ {ext.latency_ms}ms
                          </span>
                        )}
                      </div>
                      <div className="ext-card-publisher-row">
                        <span className={`ext-publisher-tag publisher-${ext.publisher.toLowerCase().replace(/[^a-z0-9]/g, "-")}`}>
                          {ext.publisher}
                        </span>
                        <span className="ext-version-badge">v{ext.version}</span>
                      </div>
                    </div>
                  </div>

                  <p className="ext-card-desc">{ext.description}</p>

                  <div className="ext-card-footer">
                    <span className={`ext-status-pill ${isEnabled ? "active" : "inactive"}`}>
                      {isEnabled ? "Ativo" : "Desativado"}
                    </span>
                    <div className="ext-card-actions">
                      <button
                        type="button"
                        className="ext-btn-secondary"
                        onClick={() => setSelectedExt(ext)}
                        title="Ver detalhes da extensão"
                      >
                        ⚙️ Config
                      </button>
                      <button
                        type="button"
                        className={`ext-btn-toggle ${isEnabled ? "disable" : "enable"}`}
                        onClick={() => toggleExt(ext.id)}
                      >
                        {isEnabled ? "Desabilitar" : "Habilitar"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}

        {recomendados.length > 0 && (
          <>
            <div className="ext-section-header recommended">
              <span>▼ Recomendados</span>
              <span className="ext-section-badge-blue">7</span>
            </div>
            {recomendados.map((ext) => {
              const isInstalled = enabledMap[ext.id] ?? false;
              return (
                <div key={ext.id} className="ext-card recommended-card">
                  <div className="ext-card-header">
                    <span className="ext-card-icon">{ext.icon}</span>
                    <div className="ext-card-titles">
                      <div className="ext-card-name-row">
                        <span className="ext-card-name">{ext.name}</span>
                        {ext.downloads && (
                          <span className="ext-card-downloads" title="Downloads no marketplace">
                            ⬇️ {ext.downloads} ★ {ext.rating}
                          </span>
                        )}
                      </div>
                      <div className="ext-card-publisher-row">
                        <span className={`ext-publisher-tag publisher-${ext.publisher.toLowerCase().replace(/[^a-z0-9]/g, "-")}`}>
                          {ext.publisher}
                        </span>
                        <span className="ext-version-badge">v{ext.version}</span>
                      </div>
                    </div>
                  </div>

                  <p className="ext-card-desc">{ext.description}</p>

                  <div className="ext-card-footer">
                    <span className="ext-status-pill inactive">Recomendado</span>
                    <div className="ext-card-actions">
                      <button
                        type="button"
                        className="ext-btn-primary-install"
                        onClick={() => toggleExt(ext.id)}
                      >
                        {isInstalled ? "✓ Instalado" : "Instalar"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* Modal / Detail Popup */}
      {selectedExt && (
        <div className="ext-details-overlay" onClick={() => setSelectedExt(null)}>
          <div className="ext-details-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ext-details-modal-header">
              <span className="ext-card-icon">{selectedExt.icon}</span>
              <div>
                <h4>{selectedExt.name}</h4>
                <span className={`ext-publisher-tag publisher-${selectedExt.publisher}`}>
                  {selectedExt.publisher}
                </span>
              </div>
              <button type="button" className="close-btn" onClick={() => setSelectedExt(null)}>
                ✕
              </button>
            </div>
            <div className="ext-details-modal-body">
              <p><strong>Descrição:</strong> {selectedExt.description}</p>
              <p><strong>Versão:</strong> {selectedExt.version}</p>
              <p><strong>Categoria:</strong> {selectedExt.category}</p>
              <p><strong>ID do Pacote:</strong> <code>{selectedExt.id}</code></p>
              {selectedExt.latency_ms && (
                <p><strong>Latência Registrada:</strong> <code>{selectedExt.latency_ms}ms</code></p>
              )}
              <div className="ext-config-section">
                <h5>Configurações de Execução</h5>
                <label className="ext-checkbox-label">
                  <input type="checkbox" defaultChecked /> Autostart junto com a IDE
                </label>
                <label className="ext-checkbox-label">
                  <input type="checkbox" defaultChecked /> Modo de verificação estrita de tipos
                </label>
              </div>
            </div>
            <div className="ext-details-modal-footer">
              <button type="button" className="packages-btn-primary" onClick={() => setSelectedExt(null)}>
                Concluído
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="packages-footer">
        <span className="status-dot active" />
        <span>Suporte Pyrefly (Meta) & Python ativado na IDE agêntica</span>
      </div>
    </div>
  );
}

// ── Containers (Docker & Container Management) ────────────────────────────

export function ContainersPanel() {
  const [data, setData] = useState<ContainerTreeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [activeLogsContainer, setActiveLogsContainer] = useState<{ id: string; name: string } | null>(null);
  const [containerLogsContent, setContainerLogsContent] = useState<string>("");
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    containers: true,
    images: true,
    registries: false,
    networks: false,
    volumes: false,
    contexts: false,
    help: true,
  });

  const carregar = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getContainerTree();
      setData(res);
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const toggleSection = (sec: string) => {
    setExpandedSections((prev) => ({ ...prev, [sec]: !prev[sec] }));
  };

  const handleAction = async (id: string, action: "start" | "stop" | "restart" | "remove") => {
    try {
      await runContainerAction(id, action);
      await carregar();
    } catch (err) {
      alert(`Falha na ação ${action}: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleOpenLogs = async (c: { id: string; name: string }) => {
    setActiveLogsContainer(c);
    setLoadingLogs(true);
    try {
      const res = await getContainerLogs(c.id);
      setContainerLogsContent(res.logs);
    } catch (err) {
      setContainerLogsContent(`Erro ao carregar logs: ${err}`);
    } finally {
      setLoadingLogs(false);
    }
  };

  return (
    <div className="containers-panel">
      <div className="containers-header">
        <div className="containers-title-group">
          <div className="containers-title-icon">🐳</div>
          <div>
            <h3 className="containers-title">Containers</h3>
            <p className="containers-subtitle">Integração Docker Daemon & Stack Compose</p>
          </div>
        </div>
        <button
          type="button"
          className="icon-action-btn"
          title="Recarregar containers e Docker daemon"
          onClick={() => void carregar()}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21.5 2v6h-6M2.5 22v-6h6" />
            <path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8M22 12.5a10 10 0 0 1-18.8 4.2L2.5 16" />
          </svg>
        </button>
      </div>

      {erro && <div className="panel-error">{erro}</div>}

      <div className="containers-scroll-tree">
        {/* Section 1: Containers */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("containers")}>
            <span className="tree-arrow">{expandedSections.containers ? "∨" : "＞"}</span>
            <span className="docker-group-title">Containers</span>
          </div>

          {expandedSections.containers && (
            <div className="docker-tree-children">
              {loading && !data ? (
                <div className="docker-empty-state">Consultando daemon Docker local...</div>
              ) : !data || Object.keys(data.containers_by_project).length === 0 ? (
                <div className="docker-empty-state">Nenhum container ativo encontrado.</div>
              ) : (
                Object.entries(data.containers_by_project).map(([proj, containers]) => (
                  <div key={proj} className="compose-project-group">
                    <div className="compose-project-header">
                      <span className="tree-arrow">∨</span>
                      <span className="compose-icon">🗃️</span>
                      <span className="compose-name">{proj}</span>
                    </div>
                    <div className="compose-containers-list">
                      {containers.map((c) => {
                        const isRunning = c.state === "running";
                        return (
                          <div key={c.id} className="container-item-row">
                            <div className="container-item-left">
                              <span className={`container-state-dot ${isRunning ? "running" : "stopped"}`} />
                              <span className="container-item-name">{c.name}</span>
                              <span className="container-item-image">{c.image}</span>
                              <span className="container-item-status">{c.status}</span>
                            </div>

                            <div className="container-item-actions">
                              <button
                                type="button"
                                className="icon-action-btn"
                                title="Ver logs do container"
                                onClick={() => void handleOpenLogs(c)}
                              >
                                📄
                              </button>
                              {isRunning ? (
                                <button
                                  type="button"
                                  className="icon-action-btn danger"
                                  title="Parar container"
                                  onClick={() => void handleAction(c.id, "stop")}
                                >
                                  ⏹
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  className="icon-action-btn success"
                                  title="Iniciar container"
                                  onClick={() => void handleAction(c.id, "start")}
                                >
                                  ▶
                                </button>
                              )}
                              <button
                                type="button"
                                className="icon-action-btn"
                                title="Reiniciar container"
                                onClick={() => void handleAction(c.id, "restart")}
                              >
                                🔄
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Section 2: Images */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("images")}>
            <span className="tree-arrow">{expandedSections.images ? "∨" : "＞"}</span>
            <span className="docker-group-title">Images</span>
          </div>

          {expandedSections.images && (
            <div className="docker-tree-children">
              {data?.images.map((img) => (
                <div key={img.id} className="docker-simple-item-row">
                  <span className="docker-item-icon">📑</span>
                  <span className="docker-item-label">{img.name}</span>
                  <span className="docker-item-meta">{img.size}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 3: Registries */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("registries")}>
            <span className="tree-arrow">{expandedSections.registries ? "∨" : "＞"}</span>
            <span className="docker-group-title">Registries</span>
          </div>
          {expandedSections.registries && (
            <div className="docker-tree-children">
              {data?.registries.map((r) => (
                <div key={r.name} className="docker-simple-item-row">
                  <span className="docker-item-icon">🌐</span>
                  <span className="docker-item-label">{r.name}</span>
                  <span className="docker-item-meta">{r.url}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 4: Networks */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("networks")}>
            <span className="tree-arrow">{expandedSections.networks ? "∨" : "＞"}</span>
            <span className="docker-group-title">Networks</span>
          </div>
          {expandedSections.networks && (
            <div className="docker-tree-children">
              {data?.networks.map((n) => (
                <div key={n.name} className="docker-simple-item-row">
                  <span className="docker-item-icon">🔀</span>
                  <span className="docker-item-label">{n.name}</span>
                  <span className="docker-item-meta">{n.driver}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 5: Volumes */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("volumes")}>
            <span className="tree-arrow">{expandedSections.volumes ? "∨" : "＞"}</span>
            <span className="docker-group-title">Volumes</span>
          </div>
          {expandedSections.volumes && (
            <div className="docker-tree-children">
              {data?.volumes.map((v) => (
                <div key={v.name} className="docker-simple-item-row">
                  <span className="docker-item-icon">💾</span>
                  <span className="docker-item-label">{v.name}</span>
                  <span className="docker-item-meta">{v.driver}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 6: Docker Contexts */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("contexts")}>
            <span className="tree-arrow">{expandedSections.contexts ? "∨" : "＞"}</span>
            <span className="docker-group-title">Docker Contexts</span>
          </div>
          {expandedSections.contexts && (
            <div className="docker-tree-children">
              {data?.contexts.map((ctx) => (
                <div key={ctx.name} className="docker-simple-item-row">
                  <span className="docker-item-icon">📍</span>
                  <span className="docker-item-label">{ctx.name}</span>
                  {ctx.current && <span className="docker-item-tag-active">Ativo</span>}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 7: Help and Feedback (from screenshot) */}
        <div className="docker-tree-group">
          <div className="docker-tree-header" onClick={() => toggleSection("help")}>
            <span className="tree-arrow">{expandedSections.help ? "∨" : "＞"}</span>
            <span className="docker-group-title">Help and Feedback</span>
          </div>
          {expandedSections.help && (
            <div className="docker-tree-children">
              {data?.help_and_feedback.map((item) => (
                <div key={item.title} className="docker-help-item-row">
                  <span className="docker-item-icon">📖</span>
                  <a href={item.url} target="_blank" rel="noopener noreferrer" className="docker-help-link">
                    {item.title}
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Container Logs Viewer Modal */}
      {activeLogsContainer && (
        <div className="ext-details-overlay" onClick={() => setActiveLogsContainer(null)}>
          <div className="ext-details-modal logs-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ext-details-modal-header">
              <span className="ext-card-icon">📄</span>
              <div>
                <h4>Logs: {activeLogsContainer.name}</h4>
                <span className="ext-version-badge">ID: {activeLogsContainer.id}</span>
              </div>
              <button type="button" className="close-btn" onClick={() => setActiveLogsContainer(null)}>
                ✕
              </button>
            </div>
            <div className="ext-details-modal-body logs-body">
              {loadingLogs ? (
                <div className="packages-status-loading">Carregando logs do container...</div>
              ) : (
                <pre className="container-logs-output">{containerLogsContent || "Nenhum log retornado."}</pre>
              )}
            </div>
            <div className="ext-details-modal-footer">
              <button type="button" className="packages-btn-primary" onClick={() => setActiveLogsContainer(null)}>
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="packages-footer">
        <span className={`status-dot ${data?.connected ? "active" : ""}`} />
        <span>
          {data?.connected
            ? "Docker daemon conectado & ativo"
            : "Docker daemon (Modo Local / Host)"}
        </span>
      </div>
    </div>
  );
}



