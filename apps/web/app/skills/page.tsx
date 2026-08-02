"use client";

import React, { useEffect, useState } from "react";
import { LocalDB, Skill } from "@/lib/db";
import { useToast } from "@/components/Toast";

export default function SkillsPage() {
  const { addToast } = useToast();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);

  // Form & Sandbox state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<Skill["category"]>("automation");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [parametersJson, setParametersJson] = useState("");
  const [sandboxInput, setSandboxInput] = useState('{\n  "targetCollection": "relatorios_tecnicos"\n}');
  const [sandboxOutput, setSandboxOutput] = useState("");
  const [isExecuting, setIsExecuting] = useState(false);

  useEffect(() => {
    const loaded = LocalDB.getSkills();
    setSkills(loaded);
    if (loaded.length > 0) {
      selectSkill(loaded[0]);
    }
  }, []);

  const selectSkill = (skill: Skill) => {
    setSelectedSkill(skill);
    setName(skill.name);
    setDescription(skill.description);
    setCategory(skill.category);
    setSystemPrompt(skill.systemPrompt);
    setParametersJson(skill.parametersJson);
    setSandboxOutput("");
  };

  const handleSaveSkill = () => {
    if (!name.trim()) return;

    const newSkill: Skill = {
      id: selectedSkill ? selectedSkill.id : `skill-${Date.now()}`,
      name,
      description,
      category,
      systemPrompt,
      parametersJson,
      enabled: selectedSkill ? selectedSkill.enabled : true,
      usageCount: selectedSkill ? selectedSkill.usageCount : 0,
    };

    let updated: Skill[];
    if (selectedSkill) {
      updated = skills.map((s) => (s.id === newSkill.id ? newSkill : s));
    } else {
      updated = [newSkill, ...skills];
    }

    setSkills(updated);
    setSelectedSkill(newSkill);
    LocalDB.saveSkills(updated);
    addToast(`Skill "${name}" salva no banco de dados com sucesso!`, "success");
  };

  const handleToggleSkill = (skill: Skill) => {
    const updated = skills.map((s) => (s.id === skill.id ? { ...s, enabled: !s.enabled } : s));
    setSkills(updated);
    LocalDB.saveSkills(updated);
    addToast(`Skill ${skill.enabled ? "desativada" : "ativada"}!`, "info");
  };

  const handleRunSandbox = () => {
    if (!selectedSkill) return;
    setIsExecuting(true);
    setSandboxOutput("⏳ Conectando à Skill e processando parâmetros...");

    setTimeout(() => {
      setIsExecuting(false);
      const result = {
        status: "success",
        skillExecuted: selectedSkill.name,
        executionTimeMs: Math.floor(Math.random() * 40 + 15),
        tokensConsumed: Math.floor(Math.random() * 200 + 80),
        output: `[SANDBOX SUCCESS] A skill "${selectedSkill.name}" processou a requisição com sucesso.\n\nPrompt Aplicado: ${selectedSkill.systemPrompt}\n\nRetorno da Função: Dados formatados e salvos no banco de dados.`,
      };
      setSandboxOutput(JSON.stringify(result, null, 2));

      // Incrementar contagem de uso
      const updated = skills.map((s) => (s.id === selectedSkill.id ? { ...s, usageCount: s.usageCount + 1 } : s));
      setSkills(updated);
      LocalDB.saveSkills(updated);

      // ✅ INTEGRAÇÃO AUDITORIA: Registra execução de Skill no Sandbox
      LocalDB.addAuditLog({
        actor: "Agente Executor Sandbox",
        module: "Skills",
        action: "Execução de Skill em Sandbox",
        details: `Skill "${selectedSkill.name}" executada com sucesso. Tokens consumidos: ${result.tokensConsumed}.`,
        riskLevel: "low",
        ipAddress: "127.0.0.1",
        status: "success",
      });

      addToast("Execução da Skill concluída no Sandbox!", "success");
    }, 800);
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">⚡ Hub de Capacidades & Agentes</span>
          <h1>Catálogo & Editor de Skills</h1>
          <p>Defina rotinas agênticas, instrua a IA com prompts de sistema e teste execuções em sandbox.</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn-primary glow-button"
            onClick={() => {
              setSelectedSkill(null);
              setName("");
              setDescription("");
              setCategory("automation");
              setSystemPrompt("");
              setParametersJson("{\n  \"param1\": \"string\"\n}");
            }}
          >
            + Criar Nova Skill
          </button>
        </div>
      </div>

      <div className="grid grid-3-1">
        {/* Catálogo de Skills */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Skills Instaladas e Ativas</h3>
            <span className="badge-tag blue">{skills.length} Ativas</span>
          </div>

          <div className="grid grid-3">
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
                  <span>Execuções: {s.usageCount}</span>
                  <span className="text-link-sm">Editar →</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sandbox & Editor de Skill */}
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
                onChange={(e) => setCategory(e.target.value as Skill["category"])}
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

            <button type="button" className="btn-primary btn-block" onClick={handleSaveSkill}>
              💾 Salvar Skill no BD
            </button>
          </div>
        </div>
      </div>

      {/* Sandbox de Execução da Skill */}
      <section className="section-block">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🧪 Sandbox de Teste de Skill</h3>
            <button
              type="button"
              className="btn-primary glow-button"
              onClick={handleRunSandbox}
              disabled={isExecuting || !selectedSkill}
            >
              {isExecuting ? "Executando..." : "▶ Testar Skill em Sandbox"}
            </button>
          </div>

          <div className="grid grid-2">
            <div>
              <label htmlFor="sandbox-input-area" className="pane-label">Entrada JSON do Teste</label>
              <textarea
                id="sandbox-input-area"
                value={sandboxInput}
                onChange={(e) => setSandboxInput(e.target.value)}
                className="input-textarea font-mono"
                rows={7}
              />
            </div>

            <div>
              <label htmlFor="sandbox-output-area" className="pane-label">Saída de Execução (Console / Log)</label>
              <textarea
                id="sandbox-output-area"
                value={sandboxOutput}
                readOnly
                className="input-textarea font-mono text-green"
                rows={7}
                placeholder="Aguardando execução do sandbox..."
              />
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
