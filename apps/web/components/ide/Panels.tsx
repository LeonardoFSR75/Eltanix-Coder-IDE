"use client";

/**
 * Painéis da barra lateral: Explorer, Busca e Git.
 *
 * Ficam juntos porque compartilham a mesma moldura e o mesmo estado de projeto;
 * separá-los em arquivos renderia três cabeçalhos e três tratamentos de erro
 * praticamente iguais.
 */

import { useCallback, useEffect, useState } from "react";
import { del, get, post } from "@/lib/client";
import { useIde } from "@/lib/ide-store";
import { ConfirmDialog, PromptDialog } from "@/components/ide/Overlays";
import { FileIcon } from "@/components/ide/FileIcons";

// ── Explorer ────────────────────────────────────────────────────────────────

interface Entry {
  path: string;
  name: string;
  is_dir: boolean;
  size_bytes: number;
}

export function Explorer() {
  const { project, openFile, active, bumpRevision, revision } = useIde();
  const [levels, setLevels] = useState<Record<string, Entry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [erro, setErro] = useState<string | null>(null);
  const [filterText, setFilterText] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number; entry: Entry | null } | null>(null);
  const [dialogo, setDialogo] = useState<
    | { tipo: "novo-arquivo" | "nova-pasta" | "renomear"; base: string; inicial: string }
    | { tipo: "excluir"; alvo: Entry }
    | null
  >(null);

  const carregar = useCallback(
    async (subpath: string) => {
      if (!project) return;
      try {
        const data = await get<{ entries: Entry[] }>(
          `/api/workspace/tree?project=${encodeURIComponent(project)}&subpath=${encodeURIComponent(subpath)}`,
        );
        setLevels((prev) => ({ ...prev, [subpath]: data.entries }));
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

  const alternar = (entry: Entry) => {
    if (!entry.is_dir) {
      openFile(entry.path);
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
      await post("/api/workspace/file", { project, path: caminho, is_dir: isDir });
      bumpRevision();
      if (!isDir) openFile(caminho);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  const renomear = async (origem: string, destino: string) => {
    if (!project) return;
    try {
      await post("/api/workspace/move", { project, source: origem, destination: destino });
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  const excluir = async (entry: Entry) => {
    if (!project) return;
    try {
      await del(
        `/api/workspace/file?project=${encodeURIComponent(project)}&path=${encodeURIComponent(entry.path)}&recursive=${entry.is_dir}`,
      );
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
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
          className={`tree-row${active === entry.path ? " active" : ""}`}
          style={{ paddingLeft: 10 + profundidade * 14 }}
          onClick={() => alternar(entry)}
          onContextMenu={(e) => {
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY, entry });
          }}
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
          style={{ marginLeft: "auto" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
        </button>
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
      <div className="tree">{renderar(".", 0)}</div>

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
            {menu.entry && (
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
      const data = await post<{
        matches: Match[];
        files_with_matches: number;
        files_searched: number;
        truncated: boolean;
      }>("/api/workspace/search", {
        project, query, regex, case_sensitive: caseSensitive,
      });
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
      const data = await post<{ files_changed: number; replacements: number }>(
        "/api/workspace/replace",
        { project, query, replacement, regex, case_sensitive: caseSensitive },
      );
      setResumo(`${data.replacements} substituições em ${data.files_changed} arquivos`);
      setMatches([]);
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="panel-body">
      <div className="search-form">
        <div className="search-input-wrapper">
          <input
            value={query}
            placeholder="Localizar no código..."
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void buscar()}
          />
          <button
            type="button"
            className={`search-toggle-replace ${showReplace ? "active" : ""}`}
            onClick={() => setShowReplace(!showReplace)}
            title="Alternar Substituir"
          >
            ↔
          </button>
        </div>

        {showReplace && (
          <input
            value={replacement}
            placeholder="Substituir por..."
            onChange={(e) => setReplacement(e.target.value)}
            className="replace-input"
          />
        )}

        <div className="search-opts-bar">
          <button
            type="button"
            className={`search-opt-chip ${caseSensitive ? "active" : ""}`}
            onClick={() => setCaseSensitive(!caseSensitive)}
            title="Diferenciar maiúsculas/minúsculas (Aa)"
          >
            Aa
          </button>
          <button
            type="button"
            className={`search-opt-chip ${regex ? "active" : ""}`}
            onClick={() => setRegex(!regex)}
            title="Usar Expressão Regular (.*)"
          >
            .*
          </button>
        </div>

        <div className="search-actions">
          <button type="button" className="primary" onClick={() => void buscar()} disabled={buscando || !query.trim()}>
            {buscando ? "buscando..." : "Buscar"}
          </button>
          {showReplace && (
            <button type="button" className="danger" onClick={() => setConfirmar(true)} disabled={!query.trim() || matches.length === 0}>
              Substituir Tudo
            </button>
          )}
        </div>
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      {resumo && <div className="tree-hint">{resumo}</div>}

      <div className="match-list">
        {matches.map((m, i) => (
          <button
            key={`${m.path}:${m.line}:${m.column}:${i}`}
            type="button"
            className="match"
            onClick={() => openFile(m.path, { line: m.line, column: m.column })}
          >
            <div className="match-path">
              {m.path}<span className="match-line">:{m.line}:{m.column}</span>
            </div>
            <div className="match-preview">{m.preview}</div>
          </button>
        ))}
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

interface GitFile {
  path: string;
  status: string;
}

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
      const [st, br] = await Promise.all([
        get<{ branch: string; dirty: boolean; files: GitFile[] }>(`/api/git/status?project=${encodeURIComponent(project)}`),
        get<{ branches: string[] }>(`/api/git/branches?project=${encodeURIComponent(project)}`),
      ]);
      setEstado(st);
      setBranches(br.branches);
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
      {erro && <div className="panel-error">{erro}</div>}
      {aviso && <div className="tree-hint">{aviso}</div>}

      {estado && (
        <>
          <div className="git-header-bar">
            <div className="git-branch">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="6" y1="3" x2="6" y2="15" />
                <circle cx="18" cy="6" r="3" />
                <circle cx="6" cy="18" r="3" />
                <path d="M18 9a9 9 0 0 1-9 9" />
              </svg>
              <select
                value={estado.branch}
                onChange={(e) => void acao(() => post("/api/git/checkout", { project, branch: e.target.value }))}
              >
                {branches.map((b) => <option key={b} value={b}>{b}</option>)}
                {!branches.includes(estado.branch) && <option value={estado.branch}>{estado.branch}</option>}
              </select>
              <button type="button" onClick={() => setNovoBranch(true)} title="Novo Branch" className="icon-action-btn">+</button>
            </div>
          </div>

          <div className="git-files-container">
            {stagedFiles.length > 0 && (
              <div className="git-group">
                <div className="git-group-title">
                  <span>Alterações Preparadas (Staged - {stagedFiles.length})</span>
                  <button
                    type="button"
                    className="git-action-sm"
                    title="Unstage All"
                    onClick={() => void acao(() => post("/api/git/unstage", { project, paths: stagedFiles.map((f) => f.path) }))}
                  >
                    −
                  </button>
                </div>
                {stagedFiles.map((f) => (
                  <div key={`staged:${f.path}`} className="git-file">
                    <button type="button" className="git-file-path" onClick={() => openFile(f.path)} title={f.path}>
                      <span className="git-badge staged">S</span>
                      {f.path}
                    </button>
                    <button
                      type="button"
                      className="git-action-sm"
                      title="Unstage"
                      onClick={() => void acao(() => post("/api/git/unstage", { project, paths: [f.path] }))}
                    >
                      −
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="git-group">
              <div className="git-group-title">
                <span>Alterações ({unstagedFiles.length})</span>
                {unstagedFiles.length > 0 && (
                  <button
                    type="button"
                    className="git-action-sm"
                    title="Stage All"
                    onClick={() => void acao(() => post("/api/git/stage", { project, paths: unstagedFiles.map((f) => f.path) }))}
                  >
                    +
                  </button>
                )}
              </div>
              {unstagedFiles.length === 0 && stagedFiles.length === 0 && (
                <div className="tree-hint">Nenhuma alteração pendente. Árvore limpa.</div>
              )}
              {unstagedFiles.map((f) => (
                <div key={`unstaged:${f.path}`} className="git-file">
                  <button type="button" className="git-file-path" onClick={() => openFile(f.path)} title={f.path}>
                    <span className={`git-badge ${f.status}`}>
                      {f.status === "modified" ? "M" : f.status === "untracked" ? "U" : f.status.slice(0, 1).toUpperCase()}
                    </span>
                    {f.path}
                  </button>
                  <button
                    type="button"
                    className="git-action-sm"
                    title="Stage"
                    onClick={() => void acao(() => post("/api/git/stage", { project, paths: [f.path] }))}
                  >
                    +
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="git-commit">
            <textarea
              value={mensagem}
              placeholder="Mensagem de commit (ex: feat: adiciona suporte a resizing)"
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
                    await post("/api/git/stage", { project, paths: unstagedFiles.map((f) => f.path) });
                  }
                  await post("/api/git/commit", { project, message: mensagem });
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
          onConfirm={(nome) => void acao(() => post("/api/git/checkout", { project, branch: nome, create: true }))}
          onClose={() => setNovoBranch(false)}
        />
      )}
    </div>
  );
}
