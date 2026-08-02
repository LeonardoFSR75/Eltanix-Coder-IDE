"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  SkillCategory,
  SkillRecord,
  createSkill,
  deleteSkill,
  listSkills,
  toggleSkill,
  updateSkill,
} from "@/lib/api/skills";
import { useToast } from "@/components/Toast";

const EMPTY_PARAMS = '{\n  "param1": "string"\n}';

export default function SkillsPage() {
  const { addToast } = useToast();
  const router = useRouter();

  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSkill, setSelectedSkill] = useState<SkillRecord | null>(null);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<SkillCategory>("automation");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [parametersJson, setParametersJson] = useState(EMPTY_PARAMS);

  const refreshSkills = useCallback(async () => {
    try {
      const loaded = await listSkills();
      setSkills(loaded);
      return loaded;
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao carregar skills.", "error");
      return [];
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    refreshSkills().then((loaded) => {
      if (loaded.length > 0) selectSkill(loaded[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectSkill = (skill: SkillRecord) => {
    setSelectedSkill(skill);
    setName(skill.name);
    setDescription(skill.description);
    setCategory(skill.category);
    setSystemPrompt(skill.system_prompt);
    setParametersJson(skill.parameters_json);
  };

  const startNewSkill = () => {
    setSelectedSkill(null);
    setName("");
    setDescription("");
    setCategory("automation");
    setSystemPrompt("");
    setParametersJson(EMPTY_PARAMS);
  };

  const handleSaveSkill = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const input = { name, description, category, system_prompt: systemPrompt, parameters_json: parametersJson };
      const saved = selectedSkill
        ? await updateSkill(selectedSkill.id, input)
        : await createSkill(input);
      setSkills((prev) => {
        const exists = prev.some((s) => s.id === saved.id);
        return exists ? prev.map((s) => (s.id === saved.id ? saved : s)) : [saved, ...prev];
      });
      setSelectedSkill(saved);
      addToast(`Skill "${saved.name}" salva.`, "success");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao salvar skill.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleSkill = async (skill: SkillRecord) => {
    try {
      const updated = await toggleSkill(skill.id);
      setSkills((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      if (selectedSkill?.id === updated.id) setSelectedSkill(updated);
      addToast(`Skill ${updated.enabled ? "ativada" : "desativada"}.`, "info");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao alternar skill.", "error");
    }
  };

  const handleDeleteSkill = async (skill: SkillRecord) => {
    try {
      await deleteSkill(skill.id);
      const updated = skills.filter((s) => s.id !== skill.id);
      setSkills(updated);
      if (selectedSkill?.id === skill.id) {
        updated.length > 0 ? selectSkill(updated[0]) : startNewSkill();
      }
      addToast("Skill removida.", "info");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao remover skill.", "error");
    }
  };

  const testInAgent = () => {
    if (!systemPrompt.trim()) {
      addToast("Defina um system prompt antes de testar no agente.", "error");
      return;
    }
    router.push(`/ide?agentPrompt=${encodeURIComponent(systemPrompt)}`);
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">⚡ Hub de Capacidades & Agentes</span>
          <h1>Catálogo & Editor de Skills</h1>
          <p>
            Defina prompts de sistema reusáveis. O agente do IDE já consegue descobrir e
            aplicar skills habilitadas sozinho, via{" "}
            <code className="inline-code">list_skills</code>/
            <code className="inline-code">get_skill</code>.
          </p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn-primary glow-button" onClick={startNewSkill}>
            + Criar Nova Skill
          </button>
        </div>
      </div>

      <div className="grid grid-3-1">
        <div className="panel-box">
          <div className="panel-header">
            <h3>Skills Cadastradas</h3>
            <span className="badge-tag blue">{skills.length}</span>
          </div>

          <div className="grid grid-3">
            {loading && <p className="text-xs text-muted">Carregando…</p>}
            {!loading && skills.length === 0 && (
              <p className="text-xs text-muted">Nenhuma skill cadastrada ainda.</p>
            )}
            {skills.map((s) => (
              <div
                key={s.id}
                className={`skill-card ${selectedSkill?.id === s.id ? "active" : ""}`}
                onClick={() => selectSkill(s)}
              >
                <div className="skill-card-header">
                  <span className="skill-category-badge">{s.category}</span>
                  <button
                    type="button"
                    className={`toggle-switch ${s.enabled ? "on" : "off"}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggleSkill(s);
                    }}
                  >
                    {s.enabled ? "ON" : "OFF"}
                  </button>
                </div>
                <h3>{s.name}</h3>
                <p>{s.description}</p>
                <div className="skill-card-footer">
                  <span>Usos: {s.usage_count}</span>
                  <span className="text-link-sm">Editar →</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel-box">
          <div className="panel-header">
            <h3>{selectedSkill ? "Editor de Skill" : "Nova Skill"}</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="skill-name-input">Nome da Skill</label>
              <input
                id="skill-name-input"
                type="text"
                className="input-text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ex: Leitor de CSV"
              />
            </div>

            <div className="form-group">
              <label htmlFor="skill-cat-select">Categoria</label>
              <select
                id="skill-cat-select"
                value={category}
                onChange={(e) => setCategory(e.target.value as SkillCategory)}
                className="input-select"
              >
                <option value="automation">Automação</option>
                <option value="analysis">Análise & Sintaxe</option>
                <option value="code">Geração de Código</option>
                <option value="web">Web Scraping & API</option>
                <option value="database">Banco de Dados & SQL</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="skill-desc-input">Descrição</label>
              <input
                id="skill-desc-input"
                type="text"
                className="input-text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="skill-prompt-area">System Prompt da Skill</label>
              <textarea
                id="skill-prompt-area"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                className="input-textarea"
                rows={3}
              />
            </div>

            <div className="form-group">
              <label htmlFor="skill-json-area">Parâmetros (JSON Schema)</label>
              <textarea
                id="skill-json-area"
                value={parametersJson}
                onChange={(e) => setParametersJson(e.target.value)}
                className="input-textarea font-mono"
                rows={3}
              />
            </div>

            <button
              type="button"
              className="btn-primary btn-block"
              onClick={handleSaveSkill}
              disabled={saving}
            >
              {saving ? "Salvando…" : "💾 Salvar Skill"}
            </button>
            {selectedSkill && (
              <button
                type="button"
                className="btn-danger-sm btn-block"
                onClick={() => handleDeleteSkill(selectedSkill)}
              >
                🗑️ Excluir Skill
              </button>
            )}
          </div>
        </div>
      </div>

      <section className="section-block">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🤖 Testar no Agente</h3>
            <button
              type="button"
              className="btn-primary glow-button"
              onClick={testInAgent}
              disabled={!systemPrompt.trim()}
            >
              ▶ Abrir no Agent Panel
            </button>
          </div>
          <p className="text-xs text-muted">
            Abre o IDE com o system prompt desta skill pré-preenchido no Agent Panel — a
            execução acontece de verdade, dentro de uma sessão do agente, não num sandbox
            simulado.
          </p>
        </div>
      </section>
    </div>
  );
}
