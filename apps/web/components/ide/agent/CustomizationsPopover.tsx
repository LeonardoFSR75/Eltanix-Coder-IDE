"use client";

/**
 * Popover de Personalizações, ancorado no ícone de engrenagem do cabeçalho.
 *
 * Não reaproveita o `Overlay` de `Overlays.tsx` — aquele é um modal de fundo
 * cheio, centralizado, certo pra QuickOpen/CommandPalette que querem atenção
 * total. Aqui o popover precisa ficar perto do botão que o abriu, e
 * `position: fixed` (calculado do botão) evita ser cortado pelo
 * `overflow: hidden` do `.agent-dock` — `position: absolute` sofreria esse
 * corte se o conteúdo for mais alto que o espaço restante do dock.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { listAgentTools, type AgentToolInfo as ToolInfo } from "@/lib/api/agent";
import { listSkills, toggleSkill, type SkillRecord } from "@/lib/api/skills";
import { listMcpServers, type MCPServerRecord } from "@/lib/api/mcp";
import { readFileOrNull, writeFile } from "@/lib/api/workspace";
import { loadHookPrefs, saveHookPrefs, type HookPrefs } from "@/lib/hook-prefs";
import { MODE_HINT, MODES, type Mode } from "./modes";

type CategoriaId = "overview" | "agents" | "skills" | "instructions" | "hooks" | "mcp" | "tools";

const CATEGORIAS: { id: CategoriaId; label: string; enabled: boolean }[] = [
  { id: "overview", label: "Visão geral", enabled: true },
  { id: "agents", label: "Agentes", enabled: true },
  { id: "skills", label: "Habilidades", enabled: true },
  { id: "instructions", label: "Instruções", enabled: true },
  { id: "hooks", label: "Hooks", enabled: true },
  { id: "mcp", label: "Servidores MCP", enabled: true },
  { id: "tools", label: "Ferramentas", enabled: true },
];

const INSTRUCTIONS_PATH = ".sicoobito/instructions.md";

export function CustomizationsPopover({
  anchorRef,
  onClose,
  mode,
  setMode,
  project,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  project: string | null;
}) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [categoria, setCategoria] = useState<CategoriaId>("overview");
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [toolsErro, setToolsErro] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillRecord[] | null>(null);
  const [skillsErro, setSkillsErro] = useState<string | null>(null);
  const [togglingSkill, setTogglingSkill] = useState<string | null>(null);
  const [mcpServers, setMcpServers] = useState<MCPServerRecord[] | null>(null);
  const [mcpErro, setMcpErro] = useState<string | null>(null);
  const [instructionsText, setInstructionsText] = useState("");
  const [instructionsLoadedFor, setInstructionsLoadedFor] = useState<string | null>(null);
  const [instructionsErro, setInstructionsErro] = useState<string | null>(null);
  const [instructionsMsg, setInstructionsMsg] = useState<string | null>(null);
  const [savingInstructions, setSavingInstructions] = useState(false);
  const [hookPrefs, setHookPrefs] = useState<HookPrefs>(() => loadHookPrefs());

  const handleToggleHookPref = (key: keyof HookPrefs) => {
    setHookPrefs((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      saveHookPrefs(next);
      return next;
    });
  };

  const posicao = useMemo(() => {
    const r = anchorRef.current?.getBoundingClientRect();
    if (!r) return { top: 60, right: 12 };
    return { top: r.bottom + 8, right: Math.max(12, window.innerWidth - r.right) };
  }, [anchorRef]);

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node) && e.target !== anchorRef.current) {
        onClose();
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [anchorRef, onClose]);

  useEffect(() => {
    if (categoria !== "tools" || tools !== null) return;
    listAgentTools()
      .then((t) => setTools(t))
      .catch((err) => setToolsErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, tools]);

  useEffect(() => {
    if (categoria !== "skills" || skills !== null) return;
    listSkills()
      .then((s) => setSkills(s))
      .catch((err) => setSkillsErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, skills]);

  useEffect(() => {
    if (categoria !== "mcp" || mcpServers !== null) return;
    listMcpServers()
      .then((s) => setMcpServers(s))
      .catch((err) => setMcpErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, mcpServers]);

  useEffect(() => {
    if (categoria !== "instructions" || !project || instructionsLoadedFor === project) return;
    readFileOrNull(project, INSTRUCTIONS_PATH)
      .then((f) => {
        setInstructionsText(f?.content ?? "");
        setInstructionsLoadedFor(project);
      })
      .catch((err) => setInstructionsErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, project, instructionsLoadedFor]);

  const handleSaveInstructions = async () => {
    if (!project) return;
    setSavingInstructions(true);
    setInstructionsErro(null);
    setInstructionsMsg(null);
    try {
      await writeFile(project, INSTRUCTIONS_PATH, instructionsText);
      setInstructionsMsg("Salvo — vale a partir da próxima sessão do agente.");
    } catch (err) {
      setInstructionsErro(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingInstructions(false);
    }
  };

  const handleToggleSkill = async (skillId: string) => {
    setTogglingSkill(skillId);
    try {
      const atualizado = await toggleSkill(skillId);
      setSkills((prev) => (prev ?? []).map((s) => (s.id === skillId ? atualizado : s)));
    } catch (err) {
      setSkillsErro(err instanceof Error ? err.message : String(err));
    } finally {
      setTogglingSkill(null);
    }
  };

  return (
    <div
      ref={popoverRef}
      className="customizations-popover"
      style={{ top: posicao.top, right: posicao.right }}
    >
      <nav className="customizations-nav">
        {CATEGORIAS.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`customizations-nav-item${categoria === c.id ? " active" : ""}`}
            disabled={!c.enabled}
            onClick={() => c.enabled && setCategoria(c.id)}
          >
            {c.label}
            {!c.enabled && <span className="pill warn">em breve</span>}
          </button>
        ))}
      </nav>

      <div className="customizations-pane">
        {categoria === "overview" && (
          <div className="customizations-overview">
            <p>
              O agente roda sobre um gateway multi-modelo local-first: cada tarefa vira uma sessão isolada
              num worktree Git próprio, com sandbox de execução e aprovação humana para ações de risco.
            </p>
            <p>Use as abas ao lado para ver os modos disponíveis e o catálogo de ferramentas do agente.</p>
          </div>
        )}

        {categoria === "agents" && (
          <div className="customizations-list">
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                className={`customizations-item customizations-item-button${m === mode ? " active" : ""}`}
                onClick={() => {
                  setMode(m);
                  onClose();
                }}
              >
                <div className="customizations-item-title">
                  {m}
                  {m === mode && <span className="pill ok">atual</span>}
                </div>
                <div className="customizations-item-desc">{MODE_HINT[m]}</div>
              </button>
            ))}
          </div>
        )}

        {categoria === "skills" && (
          <div className="customizations-list">
            {skillsErro && <div className="panel-error">{skillsErro}</div>}
            {!skills && !skillsErro && <div className="tree-hint">carregando…</div>}
            {skills && skills.length === 0 && !skillsErro && (
              <div className="tree-hint">
                Nenhuma habilidade cadastrada ainda. <Link href="/skills">Criar em /skills</Link>.
              </div>
            )}
            {(skills ?? []).map((s) => (
              <div key={s.id} className="customizations-item">
                <div className="customizations-item-title">
                  {s.name}{" "}
                  <span className={`pill ${s.enabled ? "ok" : "warn"}`}>
                    {s.enabled ? "ativa" : "desativada"}
                  </span>
                  <button
                    type="button"
                    className="theme-btn"
                    style={{ marginLeft: "auto", padding: "1px 8px", fontSize: "11px" }}
                    disabled={togglingSkill === s.id}
                    onClick={() => void handleToggleSkill(s.id)}
                  >
                    {togglingSkill === s.id ? "…" : s.enabled ? "Desativar" : "Ativar"}
                  </button>
                </div>
                <div className="customizations-item-desc">{s.description || s.category}</div>
              </div>
            ))}
            {skills && skills.length > 0 && (
              <Link href="/skills" className="text-btn-inline" style={{ display: "block", marginTop: 8 }}>
                Gerenciar habilidades em /skills
              </Link>
            )}
          </div>
        )}

        {categoria === "instructions" && (
          <div className="customizations-list">
            {!project && <div className="tree-hint">Selecione um projeto para editar as instruções.</div>}
            {project && (
              <>
                <p className="customizations-item-desc" style={{ marginBottom: 8 }}>
                  Texto livre, só para este projeto — concatenado ao system prompt do agente em toda
                  sessão nova. Guardado em <code>{INSTRUCTIONS_PATH}</code>.
                </p>
                {instructionsErro && <div className="panel-error">{instructionsErro}</div>}
                {instructionsMsg && (
                  <div className="tree-hint ok-hint" style={{ color: "var(--accent-emerald)" }}>
                    {instructionsMsg}
                  </div>
                )}
                {instructionsLoadedFor !== project && !instructionsErro && (
                  <div className="tree-hint">carregando…</div>
                )}
                {instructionsLoadedFor === project && (
                  <>
                    <textarea
                      className="studio-input"
                      style={{
                        width: "100%",
                        minHeight: 140,
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        resize: "vertical",
                      }}
                      value={instructionsText}
                      onChange={(e) => {
                        setInstructionsText(e.target.value);
                        setInstructionsMsg(null);
                      }}
                      placeholder="Ex.: nomeie variáveis em português; nunca rode migrações sem perguntar; prefira dataclasses a dicts soltos…"
                    />
                    <button
                      type="button"
                      className="theme-btn"
                      style={{ marginTop: 8 }}
                      disabled={savingInstructions}
                      onClick={() => void handleSaveInstructions()}
                    >
                      {savingInstructions ? "salvando…" : "💾 Salvar instruções"}
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        )}

        {categoria === "hooks" && (
          <div className="customizations-list">
            <p className="customizations-item-desc" style={{ marginBottom: 8 }}>
              Notificações sobre o que já acontece numa sessão do agente — nenhuma delas executa
              código, só decide se vira um toast na tela.
            </p>
            {(
              [
                { key: "notifyApproval" as const, label: "Avisar quando o agente pede aprovação" },
                { key: "notifyDone" as const, label: "Avisar quando a sessão termina" },
                { key: "notifyError" as const, label: "Avisar em erro de ferramenta" },
              ]
            ).map(({ key, label }) => (
              <label
                key={key}
                className="customizations-item"
                style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
              >
                <input
                  type="checkbox"
                  checked={hookPrefs[key]}
                  onChange={() => handleToggleHookPref(key)}
                />
                {label}
              </label>
            ))}
          </div>
        )}

        {categoria === "mcp" && (
          <div className="customizations-list">
            {mcpErro && <div className="panel-error">{mcpErro}</div>}
            {!mcpServers && !mcpErro && <div className="tree-hint">carregando…</div>}
            {mcpServers && mcpServers.length === 0 && !mcpErro && (
              <div className="tree-hint">
                Nenhum servidor MCP cadastrado ainda. <Link href="/mcp">Conectar em /mcp</Link>.
              </div>
            )}
            {(mcpServers ?? []).map((s) => (
              <div key={s.name} className="customizations-item">
                <div className="customizations-item-title">
                  {s.name}{" "}
                  <span className={`pill ${s.status === "connected" ? "ok" : s.status === "error" ? "bad" : "warn"}`}>
                    {s.status}
                  </span>
                </div>
                <div className="customizations-item-desc">
                  {s.transport} · {s.tools_count} ferramenta(s)
                  {s.error && ` · ${s.error}`}
                </div>
              </div>
            ))}
            {mcpServers && mcpServers.length > 0 && (
              <Link href="/mcp" className="text-btn-inline" style={{ display: "block", marginTop: 8 }}>
                Gerenciar servidores em /mcp
              </Link>
            )}
          </div>
        )}

        {categoria === "tools" && (
          <div className="customizations-list">
            {toolsErro && <div className="panel-error">{toolsErro}</div>}
            {!tools && !toolsErro && <div className="tree-hint">carregando…</div>}
            {(tools ?? []).map((t) => (
              <div key={t.name} className="customizations-item">
                <div className="customizations-item-title">
                  {t.name} <span className={`pill ${t.risk === "exec" ? "bad" : t.risk === "write" ? "warn" : "ok"}`}>{t.risk}</span>
                </div>
                <div className="customizations-item-desc">{t.description}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
