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

  // Recarrega a raiz e todos os níveis abertos quando algo muda no disco.
  useEffect(() => {
    if (!project) return;
    setLevels({});
    void carregar(".");
    for (const dir of expanded) void carregar(dir);
    // `expanded` de propósito fora das dependências: incluí-lo recarregaria a
    // árvore inteira a cada pasta aberta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const renderar = (subpath: string, profundidade: number) =>
    (levels[subpath] ?? []).map((entry) => (
      <div key={entry.path}>
        <button
          type="button"
          className={`tree-row${active === entry.path ? " active" : ""}`}
          style={{ paddingLeft: 8 + profundidade * 13 }}
          onClick={() => alternar(entry)}
          onContextMenu={(e) => {
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY, entry });
          }}
          title={entry.path}
        >
          <span className="tree-icon">
            {entry.is_dir ? (expanded.has(entry.path) ? "▾" : "▸") : "·"}
          </span>
          <span className="tree-name">{entry.name}</span>
        </button>
        {entry.is_dir && expanded.has(entry.path) && renderar(entry.path, profundidade + 1)}
      </div>
    ));

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
      {erro && <div className="panel-error">{erro}</div>}
      <div className="tree">{renderar(".", 0)}</div>

      {menu && (
        <>
          <div className="menu-backdrop" onClick={() => setMenu(null)} onContextMenu={(e) => { e.preventDefault(); setMenu(null); }} />
          <div className="context-menu" style={{ left: menu.x, top: menu.y }}>
            <button type="button" onClick={() => { setDialogo({ tipo: "novo-arquivo", base: pastaDe(menu.entry), inicial: "" }); setMenu(null); }}>
              Novo arquivo
            </button>
            <button type="button" onClick={() => { setDialogo({ tipo: "nova-pasta", base: pastaDe(menu.entry), inicial: "" }); setMenu(null); }}>
              Nova pasta
            </button>
            {menu.entry && (
              <>
                <button type="button" onClick={() => { setDialogo({ tipo: "renomear", base: menu.entry!.path, inicial: menu.entry!.name }); setMenu(null); }}>
                  Renomear
                </button>
                <button type="button" className="danger" onClick={() => { setDialogo({ tipo: "excluir", alvo: menu.entry! }); setMenu(null); }}>
                  Excluir
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
        <input
          value={query}
          placeholder="Buscar no projeto"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void buscar()}
        />
        <input
          value={replacement}
          placeholder="Substituir por (opcional)"
          onChange={(e) => setReplacement(e.target.value)}
        />
        <div className="search-opts">
          <label><input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} /> regex</label>
          <label><input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} /> Aa</label>
        </div>
        <div className="search-actions">
          <button type="button" className="primary" onClick={() => void buscar()} disabled={buscando || !query.trim()}>
            {buscando ? "buscando…" : "buscar"}
          </button>
          <button type="button" className="danger" onClick={() => setConfirmar(true)} disabled={!query.trim() || matches.length === 0}>
            substituir tudo
          </button>
        </div>
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      {resumo && <div className="tree-hint">{resumo}</div>}

      <div className="match-list">
        {matches.map((m, i) => (
          <button key={`${m.path}:${m.line}:${m.column}:${i}`} type="button" className="match" onClick={() => openFile(m.path)}>
            <div className="match-path">{m.path}<span className="match-line">:{m.line}</span></div>
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
  const { project, openFile, revision, bumpRevision } = useIde();
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
      bumpRevision();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    }
  };

  if (!project) return <div className="tree-hint">Selecione um projeto.</div>;

  return (
    <div className="panel-body">
      {erro && <div className="panel-error">{erro}</div>}
      {aviso && <div className="tree-hint">{aviso}</div>}

      {estado && (
        <>
          <div className="git-branch">
            <select
              value={estado.branch}
              onChange={(e) => void acao(() => post("/api/git/checkout", { project, branch: e.target.value }))}
            >
              {branches.map((b) => <option key={b} value={b}>{b}</option>)}
              {!branches.includes(estado.branch) && <option value={estado.branch}>{estado.branch}</option>}
            </select>
            <button type="button" onClick={() => setNovoBranch(true)} title="Novo branch">+</button>
          </div>

          <div className="git-files">
            {estado.files.length === 0 && <div className="tree-hint">Árvore limpa.</div>}
            {estado.files.map((f) => (
              <div key={`${f.path}:${f.status}`} className="git-file">
                <button type="button" className="git-file-path" onClick={() => openFile(f.path)} title={f.path}>
                  <span className={`git-badge ${f.status}`}>{f.status.slice(0, 1).toUpperCase()}</span>
                  {f.path}
                </button>
                <div className="git-file-actions">
                  {f.status !== "staged" ? (
                    <button type="button" onClick={() => void acao(() => post("/api/git/stage", { project, paths: [f.path] }))} title="Stage">+</button>
                  ) : (
                    <button type="button" onClick={() => void acao(() => post("/api/git/unstage", { project, paths: [f.path] }))} title="Unstage">−</button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="git-commit">
            <textarea
              value={mensagem}
              placeholder="Mensagem de commit — explique o porquê, não o quê"
              rows={3}
              onChange={(e) => setMensagem(e.target.value)}
            />
            <button
              type="button"
              className="primary"
              disabled={!mensagem.trim() || !estado.dirty}
              onClick={() =>
                void acao(async () => {
                  await post("/api/git/commit", { project, message: mensagem });
                  setMensagem("");
                }, "commit criado")
              }
            >
              commit
            </button>
          </div>
        </>
      )}

      {novoBranch && (
        <PromptDialog
          title="Nome do novo branch"
          confirmLabel="criar"
          onConfirm={(nome) => void acao(() => post("/api/git/checkout", { project, branch: nome, create: true }))}
          onClose={() => setNovoBranch(false)}
        />
      )}
    </div>
  );
}
