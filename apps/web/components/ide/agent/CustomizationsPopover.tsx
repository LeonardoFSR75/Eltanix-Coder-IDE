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
import { PanelState } from "@/components/ide/PanelState";
import { listAgentTools, type AgentToolInfo as ToolInfo } from "@/lib/api/agent";
import { listSkills, toggleSkill, type SkillRecord } from "@/lib/api/skills";
import { listMcpServers, type MCPServerRecord } from "@/lib/api/mcp";
import { readFileOrNull, writeFile } from "@/lib/api/workspace";
import {
  getApprovalPolicy,
  newEditPathRule,
  newExecCommandRule,
  updateApprovalPolicy,
  type ApprovalPolicy,
  type ApprovalRule,
} from "@/lib/api/approvalPolicy";
import {
  getContextRules,
  newContextRule,
  updateContextRules,
  type ContextRule,
  type ContextRulesConfig,
} from "@/lib/api/contextRules";
import { loadHookPrefs, saveHookPrefs, type HookPrefs } from "@/lib/hook-prefs";
import {
  createCustomMode,
  deleteCustomMode,
  listCustomModes,
  newCustomMode,
  updateCustomMode,
  type CustomMode,
  type CustomModeInput,
} from "@/lib/api/customModes";
import { ConfirmDialog } from "@/components/ide/Overlays";
import { MODE_HINT, MODES } from "./modes";

type CategoriaId =
  | "overview"
  | "agents"
  | "skills"
  | "instructions"
  | "context_rules"
  | "custom_modes"
  | "approval"
  | "hooks"
  | "mcp"
  | "tools";

const CATEGORIAS: { id: CategoriaId; label: string; enabled: boolean }[] = [
  { id: "overview", label: "Visão geral", enabled: true },
  { id: "agents", label: "Agentes", enabled: true },
  { id: "custom_modes", label: "Meus modos", enabled: true },
  { id: "skills", label: "Habilidades", enabled: true },
  { id: "instructions", label: "Instruções", enabled: true },
  { id: "context_rules", label: "Regras de contexto", enabled: true },
  { id: "approval", label: "Auto-aprovação", enabled: true },
  { id: "hooks", label: "Hooks", enabled: true },
  { id: "mcp", label: "Servidores MCP", enabled: true },
  { id: "tools", label: "Ferramentas", enabled: true },
];

const INSTRUCTIONS_PATH = ".novaai_studio/instructions.md";

export function CustomizationsPopover({
  anchorRef,
  onClose,
  mode,
  setMode,
  project,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  mode: string;
  setMode: (mode: string) => void;
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
  const [approvalPolicy, setApprovalPolicy] = useState<ApprovalPolicy | null>(null);
  const [approvalLoadedFor, setApprovalLoadedFor] = useState<string | null>(null);
  const [approvalErro, setApprovalErro] = useState<string | null>(null);
  const [approvalMsg, setApprovalMsg] = useState<string | null>(null);
  const [savingApproval, setSavingApproval] = useState(false);
  const [contextRules, setContextRules] = useState<ContextRulesConfig | null>(null);
  const [contextRulesLoadedFor, setContextRulesLoadedFor] = useState<string | null>(null);
  const [contextRulesErro, setContextRulesErro] = useState<string | null>(null);
  const [contextRulesMsg, setContextRulesMsg] = useState<string | null>(null);
  const [savingContextRules, setSavingContextRules] = useState(false);
  const [customModes, setCustomModes] = useState<CustomMode[] | null>(null);
  const [customModesErro, setCustomModesErro] = useState<string | null>(null);
  const [modoForm, setModoForm] = useState<CustomModeInput | null>(null);
  const [editingModoId, setEditingModoId] = useState<string | null>(null);
  const [savingModo, setSavingModo] = useState(false);
  const [modoErro, setModoErro] = useState<string | null>(null);
  const [modoToDelete, setModoToDelete] = useState<CustomMode | null>(null);
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
    // A aba "Meus modos" também precisa da lista de ferramentas (checklist de
    // `allowed_tools`) — mesmo carregamento preguiçoso da aba "Ferramentas".
    if ((categoria !== "tools" && categoria !== "custom_modes") || tools !== null) return;
    listAgentTools()
      .then((t) => setTools(t))
      .catch((err) => setToolsErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, tools]);

  useEffect(() => {
    if (categoria !== "custom_modes" || customModes !== null) return;
    listCustomModes()
      .then((m) => setCustomModes(m))
      .catch((err) => setCustomModesErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, customModes]);

  const handleStartCreateModo = () => {
    setModoForm(newCustomMode());
    setEditingModoId(null);
    setModoErro(null);
  };

  const handleStartEditModo = (m: CustomMode) => {
    setModoForm({
      name: m.name,
      icon: m.icon,
      description: m.description,
      allowed_tools: m.allowed_tools,
      prompt_block: m.prompt_block,
    });
    setEditingModoId(m.id);
    setModoErro(null);
  };

  const handleCancelModoForm = () => {
    setModoForm(null);
    setEditingModoId(null);
    setModoErro(null);
  };

  const handleToggleModoTool = (nome: string) => {
    setModoForm((prev) => {
      if (!prev) return prev;
      const has = prev.allowed_tools.includes(nome);
      return {
        ...prev,
        allowed_tools: has
          ? prev.allowed_tools.filter((t) => t !== nome)
          : [...prev.allowed_tools, nome],
      };
    });
  };

  const handleSaveModo = async () => {
    if (!modoForm || !modoForm.name.trim()) return;
    setSavingModo(true);
    setModoErro(null);
    try {
      const payload = { ...modoForm, name: modoForm.name.trim() };
      const salvo = editingModoId
        ? await updateCustomMode(editingModoId, payload)
        : await createCustomMode(payload);
      setCustomModes((prev) => {
        const lista = prev ?? [];
        return editingModoId
          ? lista.map((m) => (m.id === salvo.id ? salvo : m))
          : [...lista, salvo];
      });
      setModoForm(null);
      setEditingModoId(null);
    } catch (err) {
      setModoErro(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingModo(false);
    }
  };

  const handleDeleteModo = async (m: CustomMode) => {
    setSavingModo(true);
    setModoErro(null);
    try {
      await deleteCustomMode(m.id);
      setCustomModes((prev) => (prev ?? []).filter((x) => x.id !== m.id));
      if (mode === m.id) setMode("agent");
    } catch (err) {
      setModoErro(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingModo(false);
      setModoToDelete(null);
    }
  };

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

  useEffect(() => {
    if (categoria !== "approval" || !project || approvalLoadedFor === project) return;
    getApprovalPolicy(project)
      .then((p) => {
        setApprovalPolicy(p);
        setApprovalLoadedFor(project);
      })
      .catch((err) => setApprovalErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, project, approvalLoadedFor]);

  const handleSaveApproval = async () => {
    if (!project || !approvalPolicy) return;
    setSavingApproval(true);
    setApprovalErro(null);
    setApprovalMsg(null);
    try {
      // Linha em branco no textarea de prefixos vira string vazia no estado
      // local (o usuário pode estar no meio de digitar a próxima) — filtrada
      // só no momento de salvar, não a cada tecla.
      const rulesSaneadas = approvalPolicy.rules.map((r) =>
        r.kind === "exec_command_prefix"
          ? { ...r, allowed_prefixes: r.allowed_prefixes.map((p) => p.trim()).filter(Boolean) }
          : { ...r, path_glob: r.path_glob.trim() },
      );
      const salvo = await updateApprovalPolicy(project, {
        second_opinion: approvalPolicy.second_opinion,
        rules: rulesSaneadas,
      });
      setApprovalPolicy(salvo);
      setApprovalMsg("Salvo — vale a partir da próxima ferramenta WRITE/EXEC pendente.");
    } catch (err) {
      setApprovalErro(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingApproval(false);
    }
  };

  useEffect(() => {
    if (categoria !== "context_rules" || !project || contextRulesLoadedFor === project) return;
    getContextRules(project)
      .then((c) => {
        setContextRules(c);
        setContextRulesLoadedFor(project);
      })
      .catch((err) => setContextRulesErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, project, contextRulesLoadedFor]);

  const handleSaveContextRules = async () => {
    if (!project || !contextRules) return;
    setSavingContextRules(true);
    setContextRulesErro(null);
    setContextRulesMsg(null);
    try {
      // Regra com glob vazio (linha em branco enquanto o usuário digita) não
      // vai para o arquivo — só filtrada no momento de salvar, mesmo padrão
      // já usado pelos prefixos de comando na aba Auto-aprovação.
      const regrasSaneadas = contextRules.rules
        .map((r) => ({ glob: r.glob.trim(), instructions: r.instructions.trim() }))
        .filter((r) => r.glob && r.instructions);
      const salvo = await updateContextRules(project, regrasSaneadas);
      setContextRules(salvo);
      setContextRulesMsg("Salvo — vale a partir da próxima sessão do agente.");
    } catch (err) {
      setContextRulesErro(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingContextRules(false);
    }
  };

  const handleAddContextRule = (rule: ContextRule) => {
    setContextRules((prev) => (prev ? { ...prev, rules: [...prev.rules, rule] } : prev));
    setContextRulesMsg(null);
  };

  const handleRemoveContextRule = (index: number) => {
    setContextRules((prev) =>
      prev ? { ...prev, rules: prev.rules.filter((_, i) => i !== index) } : prev,
    );
    setContextRulesMsg(null);
  };

  const handleUpdateContextRule = (index: number, rule: ContextRule) => {
    setContextRules((prev) =>
      prev ? { ...prev, rules: prev.rules.map((r, i) => (i === index ? rule : r)) } : prev,
    );
    setContextRulesMsg(null);
  };

  const handleAddRule = (rule: ApprovalRule) => {
    setApprovalPolicy((prev) => (prev ? { ...prev, rules: [...prev.rules, rule] } : prev));
    setApprovalMsg(null);
  };

  const handleRemoveRule = (index: number) => {
    setApprovalPolicy((prev) =>
      prev ? { ...prev, rules: prev.rules.filter((_, i) => i !== index) } : prev,
    );
    setApprovalMsg(null);
  };

  const handleUpdateRule = (index: number, rule: ApprovalRule) => {
    setApprovalPolicy((prev) =>
      prev ? { ...prev, rules: prev.rules.map((r, i) => (i === index ? rule : r)) } : prev,
    );
    setApprovalMsg(null);
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
            {skillsErro && <PanelState kind="error" message={skillsErro} />}
            {!skills && !skillsErro && <PanelState kind="loading" message="carregando…" />}
            {skills && skills.length === 0 && !skillsErro && (
              <PanelState
                kind="empty"
                message={
                  <>
                    Nenhuma habilidade cadastrada ainda. <Link href="/skills">Criar em /skills</Link>.
                  </>
                }
              />
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
            {!project && <PanelState kind="empty" message="Selecione um projeto para editar as instruções." />}
            {project && (
              <>
                <p className="customizations-item-desc" style={{ marginBottom: 8 }}>
                  Texto livre, só para este projeto — concatenado ao system prompt do agente em toda
                  sessão nova. Guardado em <code>{INSTRUCTIONS_PATH}</code>.
                </p>
                {instructionsErro && <PanelState kind="error" message={instructionsErro} />}
                {instructionsMsg && (
                  <div className="tree-hint ok-hint" style={{ color: "var(--accent-emerald)" }}>
                    {instructionsMsg}
                  </div>
                )}
                {instructionsLoadedFor !== project && !instructionsErro && (
                  <PanelState kind="loading" message="carregando…" />
                )}
                {instructionsLoadedFor === project && (
                  <>
                    <textarea
                      className="studio-input"
                      style={{
                        width: "100%",
                        minHeight: 140,
                        fontFamily: "var(--font-mono)",
                        fontSize: 11.5,
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

        {categoria === "context_rules" && (
          <div className="customizations-list">
            {!project && (
              <PanelState kind="empty" message="Selecione um projeto para configurar regras de contexto." />
            )}
            {project && (
              <>
                <p className="customizations-item-desc" style={{ marginBottom: 8 }}>
                  Instruções extras injetadas no agente só quando o arquivo/pasta em foco da
                  sessão bate no glob (estilo <code>.cursor/rules</code>). Avaliado uma vez no
                  início da sessão. Guardado em <code>.novaai_studio/context_rules.yaml</code>.
                </p>
                {contextRulesErro && <PanelState kind="error" message={contextRulesErro} />}
                {contextRulesMsg && (
                  <div className="tree-hint ok-hint" style={{ color: "var(--accent-emerald)" }}>
                    {contextRulesMsg}
                  </div>
                )}
                {contextRulesLoadedFor !== project && !contextRulesErro && (
                  <PanelState kind="loading" message="carregando…" />
                )}
                {contextRulesLoadedFor === project && contextRules && (
                  <>
                    {contextRules.rules.length === 0 && (
                      <PanelState
                        kind="empty"
                        message="Nenhuma regra ainda — nenhuma instrução condicional é injetada."
                      />
                    )}

                    {contextRules.rules.map((rule, i) => (
                      <div key={i} className="customizations-item">
                        <div className="customizations-item-title">
                          Regra de contexto
                          <button
                            type="button"
                            className="theme-btn"
                            style={{ marginLeft: "auto", padding: "1px 8px", fontSize: "11px" }}
                            onClick={() => handleRemoveContextRule(i)}
                          >
                            ✕ remover
                          </button>
                        </div>
                        <input
                          className="studio-input"
                          style={{ width: "100%", marginTop: 4 }}
                          placeholder="glob, ex: apps/api/**/*.py"
                          value={rule.glob}
                          onChange={(e) =>
                            handleUpdateContextRule(i, { ...rule, glob: e.target.value })
                          }
                        />
                        <textarea
                          className="studio-input"
                          style={{
                            width: "100%",
                            minHeight: 60,
                            fontFamily: "var(--font-mono)",
                            fontSize: 11.5,
                            resize: "vertical",
                            marginTop: 4,
                          }}
                          placeholder="instruções aplicadas quando o foco bater neste glob"
                          value={rule.instructions}
                          onChange={(e) =>
                            handleUpdateContextRule(i, { ...rule, instructions: e.target.value })
                          }
                        />
                      </div>
                    ))}

                    <button
                      type="button"
                      className="theme-btn"
                      style={{ marginTop: 8 }}
                      onClick={() => handleAddContextRule(newContextRule())}
                    >
                      + regra de contexto
                    </button>

                    <button
                      type="button"
                      className="theme-btn"
                      style={{ marginTop: 8, marginLeft: 8 }}
                      disabled={savingContextRules}
                      onClick={() => void handleSaveContextRules()}
                    >
                      {savingContextRules ? "salvando…" : "💾 Salvar regras"}
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        )}

        {categoria === "custom_modes" && (
          <div className="customizations-list">
            <p className="customizations-item-desc" style={{ marginBottom: 8 }}>
              Modos próprios: nome, ícone, ferramentas permitidas e um bloco de prompt fixo.
              Selecionar um modo customizado troca <code>mode</code> para o id dele — funciona
              igual a escolher Agent/Ask/Plan.
            </p>
            {customModesErro && <PanelState kind="error" message={customModesErro} />}
            {modoErro && <PanelState kind="error" message={modoErro} />}
            {!customModes && !customModesErro && <PanelState kind="loading" message="carregando…" />}
            {customModes && customModes.length === 0 && !modoForm && (
              <PanelState kind="empty" message="Nenhum modo customizado ainda." />
            )}

            {(customModes ?? []).map((m) => (
              <div
                key={m.id}
                className={`customizations-item${m.id === mode ? " active" : ""}`}
              >
                <div className="customizations-item-title">
                  <button
                    type="button"
                    className="customizations-item-button"
                    style={{ all: "unset", cursor: "pointer", flex: 1 }}
                    onClick={() => {
                      setMode(m.id);
                      onClose();
                    }}
                  >
                    {m.icon} {m.name}
                    {m.id === mode && <span className="pill ok">atual</span>}
                  </button>
                  <button
                    type="button"
                    className="theme-btn"
                    style={{ padding: "1px 8px", fontSize: "11px" }}
                    onClick={() => handleStartEditModo(m)}
                  >
                    editar
                  </button>
                  <button
                    type="button"
                    className="theme-btn"
                    style={{ padding: "1px 8px", fontSize: "11px", marginLeft: 4 }}
                    onClick={() => setModoToDelete(m)}
                  >
                    remover
                  </button>
                </div>
                <div className="customizations-item-desc">
                  {m.description || `${m.allowed_tools.length} ferramenta(s) permitida(s)`}
                </div>
              </div>
            ))}

            {!modoForm && (
              <button type="button" className="theme-btn" style={{ marginTop: 8 }} onClick={handleStartCreateModo}>
                + criar modo
              </button>
            )}

            {modoForm && (
              <div className="customizations-item" style={{ marginTop: 8 }}>
                <div className="customizations-item-title">
                  {editingModoId ? "Editar modo" : "Novo modo"}
                </div>
                <input
                  className="studio-input"
                  style={{ width: "100%", marginTop: 4 }}
                  placeholder="nome do modo"
                  value={modoForm.name}
                  onChange={(e) => setModoForm({ ...modoForm, name: e.target.value })}
                />
                <input
                  className="studio-input"
                  style={{ width: "100%", marginTop: 4 }}
                  placeholder="ícone (emoji)"
                  value={modoForm.icon}
                  onChange={(e) => setModoForm({ ...modoForm, icon: e.target.value })}
                />
                <input
                  className="studio-input"
                  style={{ width: "100%", marginTop: 4 }}
                  placeholder="descrição curta"
                  value={modoForm.description}
                  onChange={(e) => setModoForm({ ...modoForm, description: e.target.value })}
                />
                <textarea
                  className="studio-input"
                  style={{
                    width: "100%",
                    minHeight: 80,
                    fontFamily: "var(--font-mono)",
                    fontSize: 11.5,
                    resize: "vertical",
                    marginTop: 4,
                  }}
                  placeholder="bloco de prompt sempre injetado quando este modo estiver ativo"
                  value={modoForm.prompt_block}
                  onChange={(e) => setModoForm({ ...modoForm, prompt_block: e.target.value })}
                />

                <div className="customizations-item-desc" style={{ marginTop: 8, marginBottom: 4 }}>
                  Ferramentas permitidas
                </div>
                {toolsErro && <PanelState kind="error" message={toolsErro} />}
                {!tools && !toolsErro && <PanelState kind="loading" message="carregando ferramentas…" />}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {(tools ?? []).map((t) => (
                    <label
                      key={t.name}
                      style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11.5 }}
                    >
                      <input
                        type="checkbox"
                        checked={modoForm.allowed_tools.includes(t.name)}
                        onChange={() => handleToggleModoTool(t.name)}
                      />
                      {t.name}
                    </label>
                  ))}
                </div>

                <button
                  type="button"
                  className="theme-btn"
                  style={{ marginTop: 8 }}
                  disabled={savingModo || !modoForm.name.trim()}
                  onClick={() => void handleSaveModo()}
                >
                  {savingModo ? "salvando…" : "💾 Salvar modo"}
                </button>
                <button
                  type="button"
                  className="theme-btn"
                  style={{ marginTop: 8, marginLeft: 8 }}
                  onClick={handleCancelModoForm}
                >
                  cancelar
                </button>
              </div>
            )}

            {modoToDelete && (
              <ConfirmDialog
                danger
                message={`Remover o modo customizado '${modoToDelete.name}'?`}
                onConfirm={() => void handleDeleteModo(modoToDelete)}
                onClose={() => setModoToDelete(null)}
              />
            )}
          </div>
        )}

        {categoria === "approval" && (
          <div className="customizations-list">
            {!project && (
              <PanelState kind="empty" message="Selecione um projeto para configurar a auto-aprovação." />
            )}
            {project && (
              <>
                <p className="customizations-item-desc" style={{ marginBottom: 8 }}>
                  Regras opt-in que dispensam a pausa de aprovação para ações WRITE/EXEC — restritas ao
                  que descrevem explicitamente, qualquer ambiguidade continua pausando como sempre.
                  Guardado em <code>.novaai_studio/approval_policy.yaml</code>.
                </p>
                {approvalErro && <PanelState kind="error" message={approvalErro} />}
                {approvalMsg && (
                  <div className="tree-hint ok-hint" style={{ color: "var(--accent-emerald)" }}>
                    {approvalMsg}
                  </div>
                )}
                {approvalLoadedFor !== project && !approvalErro && (
                  <PanelState kind="loading" message="carregando…" />
                )}
                {approvalLoadedFor === project && approvalPolicy && (
                  <>
                    <label
                      className="customizations-item"
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        cursor: "pointer",
                        marginBottom: 8,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={approvalPolicy.second_opinion}
                        onChange={(e) =>
                          setApprovalPolicy((prev) =>
                            prev ? { ...prev, second_opinion: e.target.checked } : prev,
                          )
                        }
                      />
                      Pedir segunda opinião automática antes de aprovar (consultiva — nunca aprova
                      sozinha)
                    </label>

                    {approvalPolicy.rules.length === 0 && (
                      <PanelState
                        kind="empty"
                        message="Nenhuma regra ainda — toda ação WRITE/EXEC continua pausando para aprovação."
                      />
                    )}

                    {approvalPolicy.rules.map((rule, i) => (
                      <div key={i} className="customizations-item">
                        {rule.kind === "edit_path_glob" ? (
                          <>
                            <div className="customizations-item-title">
                              Edição de arquivo
                              <button
                                type="button"
                                className="theme-btn"
                                style={{ marginLeft: "auto", padding: "1px 8px", fontSize: "11px" }}
                                onClick={() => handleRemoveRule(i)}
                              >
                                ✕ remover
                              </button>
                            </div>
                            <div style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
                              <input
                                className="studio-input"
                                style={{ flex: "1 1 160px" }}
                                placeholder="glob do caminho, ex: docs/*.md"
                                value={rule.path_glob}
                                onChange={(e) => handleUpdateRule(i, { ...rule, path_glob: e.target.value })}
                              />
                              <input
                                className="studio-input"
                                type="number"
                                min={1}
                                style={{ width: 90 }}
                                value={rule.max_changed_lines}
                                onChange={(e) =>
                                  handleUpdateRule(i, {
                                    ...rule,
                                    max_changed_lines: Number(e.target.value) || 1,
                                  })
                                }
                              />
                            </div>
                            <div className="customizations-item-desc" style={{ marginTop: 4 }}>
                              até {rule.max_changed_lines} linha(s) alterada(s), ferramentas:{" "}
                              {rule.tools.join(", ")}
                            </div>
                          </>
                        ) : (
                          <>
                            <div className="customizations-item-title">
                              Comando de shell
                              <button
                                type="button"
                                className="theme-btn"
                                style={{ marginLeft: "auto", padding: "1px 8px", fontSize: "11px" }}
                                onClick={() => handleRemoveRule(i)}
                              >
                                ✕ remover
                              </button>
                            </div>
                            <textarea
                              className="studio-input"
                              style={{
                                width: "100%",
                                minHeight: 50,
                                fontFamily: "var(--font-mono)",
                                fontSize: 11.5,
                                resize: "vertical",
                                marginTop: 4,
                              }}
                              placeholder={"um prefixo por linha, ex:\nnpm test\npytest"}
                              value={rule.allowed_prefixes.join("\n")}
                              onChange={(e) =>
                                handleUpdateRule(i, {
                                  ...rule,
                                  allowed_prefixes: e.target.value.split("\n"),
                                })
                              }
                            />
                          </>
                        )}
                      </div>
                    ))}

                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <button
                        type="button"
                        className="theme-btn"
                        onClick={() => handleAddRule(newEditPathRule())}
                      >
                        + regra de edição
                      </button>
                      <button
                        type="button"
                        className="theme-btn"
                        onClick={() => handleAddRule(newExecCommandRule())}
                      >
                        + regra de comando
                      </button>
                    </div>

                    <button
                      type="button"
                      className="theme-btn"
                      style={{ marginTop: 8 }}
                      disabled={savingApproval}
                      onClick={() => void handleSaveApproval()}
                    >
                      {savingApproval ? "salvando…" : "💾 Salvar política"}
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
            {mcpErro && <PanelState kind="error" message={mcpErro} />}
            {!mcpServers && !mcpErro && <PanelState kind="loading" message="carregando…" />}
            {mcpServers && mcpServers.length === 0 && !mcpErro && (
              <PanelState
                kind="empty"
                message={
                  <>
                    Nenhum servidor MCP cadastrado ainda. <Link href="/mcp">Conectar em /mcp</Link>.
                  </>
                }
              />
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
            {toolsErro && <PanelState kind="error" message={toolsErro} />}
            {!tools && !toolsErro && <PanelState kind="loading" message="carregando…" />}
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
