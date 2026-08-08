"use client";

/**
 * Painéis da barra lateral: Explorer, Busca e Git.
 *
 * Ficam juntos porque compartilham a mesma moldura e o mesmo estado de projeto;
 * separá-los em arquivos renderia três cabeçalhos e três tratamentos de erro
 * praticamente iguais.
 */

import { useCallback, useEffect, useRef, useState } from "react";
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
