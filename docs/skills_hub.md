# 🌐 Hermes Skills Hub & Governança de Agentes

Documentação oficial da arquitetura de habilidades (Skills), regras de planejamento e governança de agentes no **Eltanix Coder IDE**.

---

## 🏛️ 1. Arquitetura do Hub de Skills (`.agents/skills/`)

O ecossistema de agentes opera com uma taxonomia hierárquica baseada em **Skills Mestres (Hubs)** que roteiam a execução para **Skills Especializadas**.

```
.agents/skills/
├── master-dev/                     [Skill Mestra: Desenvolvimento]
│   ├── SKILL.md
│   ├── dev-fullstack-architecture/  [Especializada: APIs, Schemas & Desacoplamento]
│   ├── dev-testing-automation/      [Especializada: Pytest, Vitest & Cobertura]
│   └── dev-code-refactoring/        [Especializada: Clean Code, DRY & Performance]
│
├── master-security/                [Skill Mestra: Segurança da Informação]
│   ├── SKILL.md
│   ├── sec-vulnerability-audit/     [Especializada: SAST, OWASP Top 10 & CVEs]
│   └── sec-auth-sandboxing/         [Especializada: SSRF, Sandbox & Auth Tokens]
│
├── master-ai/                      [Skill Mestra: Inteligência Artificial & LLMs]
│   ├── SKILL.md
│   ├── ai-prompt-rag-engineering/   [Especializada: RAG Vetorial/Grafo & Prompts]
│   └── ai-agentic-orchestration/    [Especializada: LangGraph & Subagentes]
│
└── master-creativity/              [Skill Mestra: Criatividade & UI/UX]
    ├── SKILL.md
    ├── creative-ui-ux-design/       [Especializada: Design System, HSL & Glassmorphism]
    └── creative-content-ideation/   [Especializada: Copywriting & Diagramas Mermaid]
```

---

## 📐 2. Diretrizes do Modo Planejamento (`.agents/rules/planning_mode.md`)

Para garantir que a inteligência do agente atue com precisão cirúrgica sem gerar redundâncias ou prolixidade:

1. **Investigação Baseada no Código Existente**:
   - Inspeção obrigatória do repositório real, ADRs (`docs/adr/`) e [`CLAUDE.md`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/CLAUDE.md) antes de qualquer proposta.
2. **Propostas Objetivas e Sem Snippets Genéricos**:
   - Mapeamento explícito dos arquivos afetados (`[MODIFY]`, `[NEW]`, `[DELETE]`), evitando trechos teóricos ou boilerplate desnecessário no plano.
3. **Bloqueio de Ferramentas de Escrita até o Registro do Plano**:
   - O primeiro turno nos modos `plan` e `orchestra` exige obrigatoriamente a chamada de `write_todos` para desbloquear as ferramentas de edição e execução (`write_file`, `edit_file`, `run_command`).

---

## 📦 3. Gestão de Dependências & Prevenção de Conflitos (`manage_packages`)

### 3.1 Padronização da Stack Backend
- **Backend Python Padrão**: O repositório utiliza **FastAPI** + Pydantic v2. Tentativas indevidas de instalação de frameworks concorrentes/legados (ex.: Flask ou Django) são barradas via prompt mestre e alertas ativos.

### 3.2 Ações da Ferramenta `manage_packages`
| Ação | Descrição | Classe de Risco |
| :--- | :--- | :--- |
| `list` | Lista dependências instaladas com detecção ativa de conflito de stack. | `READ` |
| `install` | Instala pacotes no `.venv` e atualiza `requirements.txt`. | `WRITE` |
| `uninstall` | Remove dependências do `.venv` e do manifesto. | `WRITE` |
| `sync` | Sincroniza o ambiente com o manifesto oficial. | `WRITE` |
| `audit` | Varre CVEs conhecidas nas dependências. | `READ` |
| `clean` | **Purga pacotes órfãos do `.venv`** que não estão declarados em `requirements.txt`. | `WRITE` |

---

## 🔗 Referências & ADRs Relacionados
- [`CLAUDE.md`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/CLAUDE.md) — Guia geral de engenharia e protocolo de consulta.
- [`docs/ide_capabilities.md`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/ide_capabilities.md) — Estratificação de capacidades e ferramentas da IDE agêntica.
- [`docs/adr/0004-orquestracao-multiagente.md`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/adr/0004-orquestracao-multiagente.md) — ADR de Orquestração Multiagente.
