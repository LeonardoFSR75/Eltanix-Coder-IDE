# 🛠️ Capacidades e Estratificação da IDE Agêntica (Eltanix Coder IDE)

Este documento estratifica a arquitetura, ferramentas, classes de risco, fluxos de trabalho e restrições da **IDE Agêntica Local-First Eltanix Coder IDE** por tipo de funcionalidade.

---

## 📑 Sumário por Tipo

1. [📦 Pacotes (Package Management & Stack Governance)](#1--pacotes-package-management--stack-governance)
2. [🔌 Extensão (Plugins, Skills & MCP Ecosystem)](#2--extensão-plugins-skills--mcp-ecosystem)
3. [🌐 Browser (Navegação Interna & Automação Web)](#3--browser-navegação-interna--automação-web)
4. [📋 Plan (Modo Planejamento & Governança de Workflow)](#4--plan-modo-planejamento--governança-de-workflow)
5. [🤖 Agente (Orquestração Multiagente & Roteamento LLM)](#5--agente-orquestração-multiagente--roteamento-llm)
6. [💬 Ask (Human-in-the-Loop & Diálogo Interativo)](#6--ask-human-in-the-loop--diálogo-interativo)
7. [💻 Terminal (Sandbox de Execução & Processos em Segundo Plano)](#7--terminal-sandbox-de-execução--processos-em-segundo-plano)
8. [🐛 Debug (Observabilidade, Testes & Diagnósticos)](#8--debug-observabilidade-testes--diagnósticos)
9. [🧠 RAG & Segundo Cérebro (Grafo de Conhecimento e Ingestão)](#9--rag--segundo-cérebro-grafo-de-conhecimento-e-ingestão)
10. [🛡️ Segurança & Sandboxing (Políticas e Classes de Risco)](#10--segurança--sandboxing-políticas-e-classes-de-risco)
11. [✍️ Editor (Inteligência Inline: Ghost Text, Next-Edit & Cmd+K)](#11--editor-inteligência-inline-ghost-text-next-edit--cmd-k)

---

## 1. 📦 Pacotes (Package Management & Stack Governance)

Gestão de dependências e imposição de padrões da stack no ecossistema backend e frontend.

- **Ferramenta Principal**: `manage_packages`
- **Ambiente Backend**: Python no `.venv` gerenciado via `uv` e `requirements.txt`.
- **Ambiente Frontend**: Node.js/TypeScript gerenciado via `bun` e `package.json`.
- **Invariante de Stack**: O backend utiliza exclusivamente **FastAPI + Pydantic v2**. Tentativas de instalação de frameworks concorrentes (ex: Flask, Django) são bloqueadas pela governança ativada.

### Ações da Ferramenta `manage_packages`
| Ação | Descrição | Classe de Risco |
| :--- | :--- | :--- |
| `list` | Lista pacotes e verifica conformidade com a stack oficial. | `READ` |
| `install` | Instala dependências no ambiente virtual e sincroniza manifesto. | `WRITE` |
| `uninstall` | Remove dependências e atualiza manifestos. | `WRITE` |
| `sync` | Reconcilia o `.venv` com as dependências do manifesto. | `WRITE` |
| `audit` | Varre vulnerabilidades conhecidas (CVEs) nas dependências. | `READ` |
| `clean` | Purga pacotes órfãos do `.venv` ausentes no manifesto. | `WRITE` |

---

## 2. 🔌 Extensão (Plugins, Skills & MCP Ecosystem)

Mecanismos de extensão modular do comportamento agêntico através de Skills, servidores MCP e extensões VS Code / Open-VSX.

- **Hub de Skills (`.agents/skills/`)**: Taxonomia hierárquica dividida entre Skills Mestres e Skills Especializadas.
  - **`master-dev`**: Desenvolvimento fullstack, refatoração e testes.
  - **`master-security`**: Auditoria SAST/DAST, controle de acesso e sandboxing.
  - **`master-ai`**: RAG vetorial/grafo, engenharia de prompts e orquestração.
  - **`master-creativity`**: UI/UX design, copywriting e diagramação Mermaid.
- **Ecossistema MCP (`config/mcp.yaml`)**: Protocolo de contexto padronizado (Model Context Protocol). Servidores externos conectam-se dinamicamente declarando `trust_annotations` e sugestões de permissão.
- **Motor Open-VSX**: Suporte a extensões e atualizações automáticas via manifesto ([ADR 0009](adr/0009-sistema-de-extensoes-e-auto-update-open-vsx.md)).

---

## 3. 🌐 Browser (Navegação Interna & Automação Web)

Infraestrutura de navegação híbrida para automação, captura de telas e visualização de páginas web.

- **Ferramentas**: `browser_subagent`, `read_url_content`, scraping via Firecrawl.
- **Modo Híbrido ([ADR 0007](adr/0007-navegador-interno-e-emulacao-visual.md))**:
  - **Modo Live**: Iframe em sandbox com suporte a HMR (Hot Module Replacement) para pré-visualização em tempo real.
  - **Modo Headless**: Automação com Playwright/CDP e emulação ultrarrápida via Lightpanda para inspeção de DOM pelo agente.
- **Proteção Anti-SSRF ([ADR 0006](adr/0006-integracao-firecrawl-web-rag.md))**: Validação de URLs por `validate_target_url()`, bloqueando endereços IP privados (RFC 1918), loopback, metadados cloud e redes de contêineres Docker.

---

## 4. 📋 Plan (Modo Planejamento & Governança de Workflow)

Workflow rigoroso de 5 etapas para execução segura de alterações de software.

- **Fluxo de Trabalho**:
  1. **Pesquisa**: Leitura e inspeção do código e do grafo de conhecimento (Obsidian/Graphify).
  2. **Plano de Implementação**: Criação ou atualização do artefato `implementation_plan.md`.
  3. **Aprovação do Usuário**: Pausa na execução até o aceite explícito do plano.
  4. **Execução**: Implementação cirúrgica com acompanhamento das mudanças propostas.
  5. **Validação**: Verificação dos testes e documentação dos resultados em `walkthrough.md`.
- **Regra de Desbloqueio (`.agents/rules/planning_mode.md`)**: No modo de planejamento, chamadas às ferramentas de gravação/execução (`write_file`, `edit_file`, `run_command`) exigem o registro inicial em `write_todos`.

---

## 5. 🤖 Agente (Orquestração Multiagente & Roteamento LLM)

Arquitetura de inteligência agêntica baseada em LangGraph e roteamento centralizado de modelos.

- **Gate de LLM Único ([ADR 0001](adr/0001-camada-unica-de-llm.md))**: NENHUM módulo consome APIs diretas de provedores (OpenAI, Anthropic, Gemini). Todo o tráfego passa obrigatoriamente por `eltanix.router` (`RouterEngine.complete()` / `.embed()`).
- **Orquestração Multiagente ([ADR 0004](adr/0004-orquestracao-multiagente.md))**:
  - Despacho de subagentes autônomos para tarefas paralelas e isoladas.
  - Persistência do estado do agente no PostgreSQL.
  - Interrupção configurada para controle humano de passos críticos.

---

## 6. 💬 Ask (Human-in-the-Loop & Diálogo Interativo)

Interface de diálogo interativo para eliminação de ambiguidades e aprovação de riscos.

- **Ferramentas**: `ask_question`, `interrupt()` do LangGraph.
- **Aplicações**:
  - **Solicitação de Feedback**: Questionários de múltipla escolha renderizados na UI para decisões de design ou arquitetura.
  - **Gatilho Human-in-the-Loop**: Qualquer ferramenta com classe de risco `WRITE` ou `EXEC` pode pausar a execução aguardando aprovação explícita do usuário na interface.

---

## 7. 💻 Terminal (Sandbox de Execução & Processos em Segundo Plano)

Ambiente isolado para execução de comandos do sistema operacional, tarefas contínuas e temporizadores.

- **Ferramentas**: `run_command`, `manage_task`, `schedule`.
- **Isolamento de Execução ([ADR 0002](adr/0002-executor-isolado.md))**:
  - O daemon Docker da API não executa comandos do usuário diretamente.
  - As chamadas de terminal são encaminhadas para o serviço `executor` isolado.
  - Sandbox configurado com usuário não-root, `cap_drop: ALL`, rede desabilitada e autenticação via `EXECUTOR_TOKEN`.
- **Mensageria Assíncrona**: O agente inicia tarefas em background sem polling, recebendo notificações reativas no término ou em log events.

---

## 8. 🐛 Debug (Observabilidade, Testes & Diagnósticos)

Ferramentas e protocolos para resolução de problemas e manutenção da qualidade do código.

- **Suíte de Ferramentas**:
  - **Chrome DevTools MCP**: Diagnóstico de acessibilidade (a11y), vazamentos de memória e métricas de performance (LCP).
  - **Test Runners**: Pytest (`apps/api`) e Vitest/Bun (`apps/web`).
  - **Observabilidade**: Logging estruturado via `structlog` injetando `request_id` e `session_id` em todos os registros HTTP e agênticos. Spans gravados em `TraceRecorder`.
- **Diretrizes de Depuração**:
  - Proibição estrita de diagnósticos sem leitura de logs completos.
  - Proibição de correções superficiais de sintomas (ex: engolir exceções, ignorar testes quebrados ou mockar dados sem investigar a causa raiz).

---

## 9. 🧠 RAG & Segundo Cérebro (Grafo de Conhecimento e Ingestão)

Sistema de recuperação de informação multi-modal e grafo de conhecimento integrados ao Obsidian.

- **Fontes Obrigatórias ([CLAUDE.md](../CLAUDE.md))**:
  - **Grafo de Conhecimento**: `graphify-out/obsidian/` com MOCs, Painel Central e Mapa Arquitetural ([ADR 0003](adr/0003-grafo-de-conhecimento-graphify.md)). Ferramenta `graph_search` para travessia de grafos em N-hops.
- **RAG Multi-Formato ([ADR 0008](adr/0008-rag-multi-formato-anydoc-e-pdf-inspector.md))**:
  - Ingestão de arquivos de escritório (Word, Excel, PowerPoint) via motor `calamine` (`firecrawl-anydoc`).
  - Inspeção de PDFs por `pdf-inspector` em Rust com fallback para `pypdf`.

---

## 10. 🛡️ Segurança & Sandboxing (Políticas e Classes de Risco)

Modelagem de ameaças e controle de privilégios em todas as operações agênticas.

- **Matriz de Classes de Risco (`RiskClass`)**:
  - `READ`: Operações idempotentes de leitura e consulta de informações (liberadas automaticamente).
  - `WRITE`: Alterações de código, arquivos ou banco de dados (exigem validação do plano ou Human-in-the-Loop).
  - `EXEC`: Execução de comandos de terminal, mutação de infraestrutura ou instalações (exigem aprovação explícita do usuário).
- **Autenticação Obrigatória ([ADR 0005](adr/0005-login-obrigatorio.md))**: Toda rota HTTP exige `AuthDep` (sessão via cookie HttpOnly ou chave `ELTANIX_API_KEY`).
- **Prevenção contra Perda de Dados (`accidental-data-loss-prevention`)**: Confirmação mandatória antes de comandos destrutivos (`DROP TABLE`, `rm -rf`, deleção de projetos/buckets).

---

## 11. ✍️ Editor (Inteligência Inline: Ghost Text, Next-Edit & Cmd+K)

Camada de assistência dentro do Monaco, entregue na **Onda 1** do roadmap ponta a ponta.

- **Autocompletar inline / ghost text ([ADR 0014](adr/0014-autocompletar-inline-ghost-text.md))**:
  cursor parado ~250 ms → sugestão cinza de 1–8 linhas, aceita com `Tab`.
  `POST /api/context/completions`, **READ-only** (não passa por `ApprovalPolicy`).
  Egress só por `RouterEngine.complete()` (`source="ide:completion"`); perfil de rota
  `completion` em `routes.yaml` (modelos tiny/locais por latência). Kill switch
  `IDE_INLINE_COMPLETIONS_ENABLED`; rate limit `IDE_COMPLETION_MAX_PER_MINUTE`.
- **Predição do próximo edit / "tab to jump" ([ADR 0015](adr/0015-predicao-do-proximo-edit.md))**:
  após uma edição assentar, o modelo prevê o próximo trecho a mudar no arquivo aberto.
  `POST /api/context/next-edit`, **READ-only**, `source="ide:next_edit"`, perfil `next-edit`.
  Precedência de `Tab`: sugestão inline (1.1) → next-edit pendente (1.2) → indentar.
  Kill switch `IDE_NEXT_EDIT_ENABLED`.
- **Cmd+K (edição inline sob demanda)**: `POST /api/agent/inline-edit` — seleção +
  instrução, streaming e accept/reject por hunk. **`WRITE`**: passa por `ApprovalPolicy`
  porque escreve arquivo.
- **Gutter intelligence (Onda 1.5)**: blame, cobertura de testes e CVEs na margem do editor.
- **Busca semântica no painel Search (Onda 1.4)**: consulta o índice `pgvector` do projeto.
- **Telemetria**: aceitação em `completion_event` (migrações 0029 e 0030, coluna `kind`
  `inline`/`next_edit`); custo/latência de cada chamada em `request_log`.
  `GET /api/context/completions/stats?days=` agrega taxa de aceitação por `kind` e linguagem.

---

## 🔗 Referências Cruzadas

- [`CLAUDE.md`](../CLAUDE.md) — Guia mestre de engenharia e diretrizes de desenvolvimento.
- [`docs/skills_hub.md`](skills_hub.md) — Arquitetura de Skills e governança dos agentes.
- [`docs/adr/`](adr/) — Registros de Decisões Arquiteturais.
