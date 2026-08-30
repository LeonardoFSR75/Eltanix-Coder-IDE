# Eltanix Coder IDE

IDE agêntica local-first: FastAPI (`apps/api`) + Next.js (`apps/web`) + Svelte 5/Tauri (`apps/desktop`), Postgres+pgvector,
Redis, MinIO, tudo via Docker Compose. Ver [README.md](README.md) para a visão de produto
e como subir a stack — este arquivo é sobre como trabalhar no código.

Guias específicos: [apps/api/CLAUDE.md](apps/api/CLAUDE.md), [apps/web/CLAUDE.md](apps/web/CLAUDE.md), [apps/desktop/CLAUDE.md](apps/desktop/CLAUDE.md), [`docs/ide_capabilities.md`](docs/ide_capabilities.md).

---

## 🧠 Protocolo de Consulta Obrigatória para Agentes de IA (Obsidian & Graphify)

> [!IMPORTANT]
> **REGRA FUNDAMENTAL PARA AGENTES (Claude, Gemini, Antigravity, Subagentes e Modelos Locais):**
> É **OBRIGATÓRIO** consultar a base de conhecimento do **Segundo Cérebro & Knowledge Graph** no Obsidian (`graphify-out/obsidian/`) e os ADRs antes de propor ou executar alterações arquiteturais, refatorações amplas, novos módulos ou modificações em segurança/roteamento.

### 📚 Fontes Obrigatórias de Consulta:
1. **Painel Central & MOCs do Obsidian (`graphify-out/obsidian/00 - 🏠 Painel & MOCs/`)**:
   - `00 - 🏠 Início (MOC Principal).md`: Dashboard mestre com visão 360°, tabela de decisões e top hubs.
   - `MOC - Arquitetura & Sistema.md` e MOCs temáticos especializados.
   - `Mapa Arquitetural Eltanix Coder IDE.canvas`: Fluxo visual interativo dos componentes.
2. **Registro de Decisões Arquiteturais (`docs/adr/` e `01 - 📑 Documentos & ADRs/`)**:
   - `ADR 0001 — Camada Única de LLM`
   - `ADR 0002 — Executor Isolado`
   - `ADR 0003 — Grafo de Conhecimento e Graph RAG (Graphify)`
   - `ADR 0004 — Orquestração Multiagente`
   - `ADR 0005 — Login Obrigatório com Sessão por Cookie`
   - `ADR 0006 — Integração Firecrawl para Web Scraping, Search e Ingestão de Docs no RAG`
   - `ADR 0007 — Navegador Interno Híbrido, Emulação de Dispositivos e Compatibilidade Lightpanda`
   - `ADR 0008 — RAG Multi-Formato Universal com AnyDoc, Motor Calamine e PDF Inspector`
   - `ADR 0009 — Sistema de Extensões e Auto-Update via Open VSX`
   - `ADR 0010 — Segurança de Servidores MCP e Cisco AI Defense Scanner`
   - `ADR 0011 — Sanitização Dinâmica de PII`
   - `ADR 0012 — Modos Customizáveis do Agente e o Gate de Ferramentas por Nome`
   - `ADR 0013 — apps/desktop Congelado até a IDE Web Cruzar a Onda 1`
3. **Histórico de Fases & Roadmap (`01 - 📑 Documentos & ADRs/Notas de Projeto (Roadmap & Fases)/`)**:
   - 20 notas sequenciais (`00-MOC.md` a `19-robustez-agente-router-orquestracao-multiagente.md`).
4. **Ferramenta `graph_search` (em tempo de execução)**:
   - Em sessões agênticas, consultar o grafo de conhecimento via ferramenta `graph_search` para mapear dependências em $N$-hops e avaliar impacto de alterações antes de gravar arquivos.

---

## Invariantes de arquitetura (não violar sem atualizar o ADR correspondente)

- **Uso Obrigatório do Grafo e Segundo Cérebro** (`docs/adr/0003-grafo-de-conhecimento-graphify.md`):
  Todo agente deve respeitar a malha relacional do repositório. Decisões arquiteturais devem ser
  registradas em ADR e refletidas no vault Obsidian (`graphify-out/obsidian/`).
- **Uma única porta de saída para LLM** (`docs/adr/0001-camada-unica-de-llm.md`): nenhum
  módulo fora de `eltanix.router` importa `litellm`/`openai`/`anthropic`/SDK de
  provedor. Todo consumo passa por `RouterEngine.complete()`/`.embed()`.
- **Execução de comando nunca fala direto com o daemon Docker da API**
  (`docs/adr/0002-executor-isolado.md`): em produção/container, `run_command` passa pelo
  serviço `executor` isolado, autenticado por `EXECUTOR_TOKEN`. As restrições de sandbox
  (usuário não-root, `cap_drop: ALL`, rede desabilitada) são fixadas *no executor*, nunca
  recebidas por parâmetro do chamador.
- **Toda ferramenta do agente declara uma `RiskClass`** (`READ`/`WRITE`/`EXEC`) em
  `agent/tools/base.py`. `WRITE`/`EXEC` sempre param no grafo (`agent/graph.py`) esperando
  aprovação humana via `interrupt()` do LangGraph — isso é decidido pela ferramenta, nunca
  pelo chamador. Ferramentas MCP (servidores externos conectados em `/mcp`) nascem `WRITE`
  por padrão; só viram `READ` se o servidor for marcado `trust_annotations: true` e a tool
  anunciar `read_only_hint: true`.
- **Proteção Anti-SSRF para chamadas Web** (`docs/adr/0006-integracao-firecrawl-web-rag.md`):
  Toda requisição externa (Firecrawl / Scrape / Deep Research) deve ser validada por `validate_target_url()`,
  bloqueando RFC 1918, loopback, metadados cloud e nomes de contêineres Docker.
- **RAG Multi-Formato em Rust Nativo** (`docs/adr/0008-rag-multi-formato-anydoc-e-pdf-inspector.md`):
  Extração de arquivos de escritório via `firecrawl-anydoc` (motor `calamine`) e classificação de PDFs
  via `pdf-inspector` com fallback transparente para `pypdf`.
- **Navegador Interno Híbrido** (`docs/adr/0007-navegador-interno-e-emulacao-visual.md`):
  Modo Live (Iframe em sandbox) para HMR e testes locais; Modo Headless (CDP / Playwright / Lightpanda)
  para automação e inspeção de DOM pelo Agente.
- **RAG tem fontes independentes** (`context/store.py`, `documents/store.py`, `notes/store.py`,
  `graphify/store.py`) — a duplicação entre as rotinas de busca é **deliberada**, documentada
  nos próprios arquivos. Não abstrair num helper compartilhado.
- **Config declarativa em YAML + editor de round-trip** (`providers.yaml`/`routes.yaml`/
  `mcp.yaml`/`mcp_catalog.yaml`): leitura simples via `yaml.safe_load` num módulo `config.py`
  do domínio, escrita via `ruamel.yaml` num `*_editor.py` separado, para preservar
  comentários do arquivo.
- **Falha de serviço opcional degrada, não derruba**: Redis fora → sem cache/circuit
  breaker; MinIO fora → upload de documento indisponível; MCP com comando inválido →
  aquele servidor marca `status: "error"`, os outros continuam.
- **Login é obrigatório para o browser** (`docs/adr/0005-login-obrigatorio.md`): toda rota
  usa `AuthDep = Depends(require_session)` (`api/deps.py`) — aceita `ELTANIX_API_KEY`
  válida OU cookie de sessão válido, e nunca fica aberta por omissão.

---

## Comandos Úteis

```bash
# Backend — testes e lint
cd apps/api && uv run pytest tests -q && uv run ruff check src

# Frontend — typecheck e build
cd apps/web && bun run typecheck && bun run build

# Docker Compose
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose logs -f api web
```

---

## Observabilidade

Logs (`structlog`) carregam `request_id` (todo request HTTP, via
`api/middleware.py::CorrelationIdMiddleware`) e `session_id` (sessões de agente, via
`agent/runner.py::stream_run`). Spans de ferramentas e RAG são gravados em `TraceRecorder` e
tabelas `request_log` no Postgres.
