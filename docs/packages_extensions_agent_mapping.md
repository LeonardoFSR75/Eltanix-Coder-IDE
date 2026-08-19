# Mapeamento: Pacotes & Extensões ↔ Agente

Este documento mapeia, camada por camada, como a gestão de **pacotes** (`.venv`/`requirements.txt`
e equivalentes por ecossistema) e de **extensões** (catálogo estilo VS Code/Open VSX) fica
acessível tanto ao **agente** (via tool-calling) quanto ao **usuário** (via painéis da IDE), e como
as duas superfícies se mantêm sincronizadas em tempo real. É o registro detalhado do trabalho
que criou/consolidou essas duas verticais — complementa a visão de survey em
[`docs/ide_capabilities.md`](ide_capabilities.md) (seção 1 e 2) e a decisão de auto-update de
extensões em [`docs/adr/0009-sistema-de-extensoes-e-auto-update-open-vsx.md`](adr/0009-sistema-de-extensoes-e-auto-update-open-vsx.md).

## 1. Visão geral do fluxo

```
                         ┌─────────────────────────┐
                         │   Backend compartilhado   │
                         │ packages/commands.py      │
                         │ extensions/manager.py     │
                         │ extensions/store.py (PG)  │
                         └───────────┬───────────────┘
                    ┌────────────────┼────────────────┐
                    │                                  │
         ┌──────────▼──────────┐          ┌────────────▼────────────┐
         │  api/routes/*.py     │          │  agent/tools/*.py        │
         │  (REST, sem worktree)│          │  (tool-call do agente,   │
         │                       │          │   com fallback worktree) │
         └──────────┬───────────┘          └────────────┬────────────┘
                    │ fetch (lib/api/*.ts)                │ SSE (stream_run)
         ┌──────────▼───────────┐          ┌────────────▼────────────┐
         │ PackagesPanel.tsx     │          │ sessionRuntime.ts        │
         │ ExtensionsPanel.tsx   │◄─────────┤ dispatch CustomEvent      │
         │ StatusBar (indicador) │  window  │ sicoobito:packages:changed│
         └────────────────────────┘  event  │ sicoobito:extensions:...  │
                                              └────────────┬────────────┘
                                                            │
                                              ┌─────────────▼────────────┐
                                              │ PackagesCard.tsx          │
                                              │ (chat do agente, inline)  │
                                              └────────────────────────────┘
```

Duas rotas de entrada — REST (usuário no painel) e tool-call (agente no chat) — convergem no
mesmo backend compartilhado, e mutações de qualquer uma das duas rotas propagam para a outra via
um evento de DOM disparado no frontend.

## 2. Backend — camada compartilhada

### 2.1 Pacotes: `packages/commands.py`

Extraído (task #5 desta fase) porque `api/routes/packages.py` (REST) e `agent/tools/packages.py`
(ferramenta do agente) reimplementavam a mesma cadeia de if/elif por ecossistema. Contém apenas o
que é **idêntico** nas duas camadas:

- `build_ecosystem_command()` — monta o `argv` de install/uninstall/sync para
  `python` (pip), `nodejs` (npm), `go`, `rust` (cargo), `php` (composer). Levanta
  `MissingBinaryError` se o binário do ecossistema não está no `PATH` do host.
- `parse_installed_packages()` — lê `package.json`/`go.mod`/`Cargo.toml`/`composer.json`
  estaticamente (sem subprocesso) para os ecossistemas não-Python.
- `list_python_packages()` — único caso que exige subprocesso assíncrono (`pip list --format=json`),
  porque a fonte de verdade do Python é o `.venv` de fato, não um manifesto estático.
- `run_dependency_audit()` / `_audit_python()` / `_audit_nodejs()` — auditoria de CVE via
  `pip-audit --format=json` ou `npm audit --json`. Go/Rust/PHP devolvem `supported: False`
  explícito em vez de fingir suporte (não há scanner CLI ubíquo para os três no host).

O que **não** é compartilhado (fica em cada chamador): timeout, resolução de caminho
(worktree → projeto canônico), e formato de erro (`HTTPException` na rota REST vs
`ToolResult.failure()` na ferramenta do agente).

### 2.2 Extensões: `extensions/manager.py` + `extensions/store.py` + `extensions/client.py`

- `MASTER_EXTENSIONS_CATALOG` (`extensions/catalog.py`) — catálogo estático em memória (id, nome,
  descrição, categoria, ícone). Nunca muda em runtime; é a única fonte de verdade sobre *quais*
  extensões existem — nem o backend REST nem o agente reimplementam essa lista (task #12: o
  frontend deixou de ter uma cópia hardcoded do catálogo, agora sempre busca do backend, com
  `PanelState kind="error"` + retry se a busca falhar em vez de mostrar dados desatualizados).
- `extensions/store.py` — overlay persistido em Postgres (migração `0022_extension_state.py`,
  task #6) para ativação (`active`), versão instalada e update pendente. Carregado uma vez no
  `lifespan` via `ExtensionsManager.hydrate()`; cada mutação (`toggle_extension`,
  `update_extension`, `set_auto_update`) regrava a linha correspondente. Substituiu um
  `config/extensions_state.json` sem lock (risco de corrupção sob escrita concorrente).
- `extensions/client.py` (`OpenVSXClient`) — busca no Open VSX Registry (`search_marketplace`,
  `check_updates_batch`). `ExtensionsManager.search_online()` cacheia o resultado em Redis por
  10 min com chave `sicoobito:cache:extensions:search:<sha256(query)>` (task #8) — sem Redis,
  degrada para busca direta, mesmo padrão de `router/health.py`.
- `ExtensionsManager.is_active(extension_id)` é consultado pelo gateway de LSP
  (`api/routes/lsp.py`) via `lsp/extension_bridge.py::LSP_SERVER_TO_EXTENSION_ID` — desativar
  `ms-python.python`, por exemplo, bloqueia a sessão do servidor `pyright` até reativação
  (task #3: essa é a ligação real entre "extensão desligada" e "language server indisponível",
  antes o toggle só mexia num JSON sem efeito no editor).

## 3. Backend — as duas portas de entrada

### 3.1 REST (`api/routes/packages.py`, `api/routes/extensions.py`)

Usada pelo `PackagesPanel`/`ExtensionsPanel` via `lib/api/packages.ts`/`lib/api/extensions.ts`
(que passam por `lib/client.ts`, único cliente HTTP do frontend). Sempre atrás de `AuthDep`.

| Rota | Ação |
| --- | --- |
| `GET /api/projects/{slug}/packages` | Lista pacotes instalados + `requirements_map` |
| `GET /api/projects/{slug}/packages/audit` | Auditoria de CVE |
| `POST /api/projects/{slug}/packages/install` | Instala + atualiza manifesto |
| `DELETE /api/projects/{slug}/packages/uninstall` | Remove + atualiza manifesto |
| `POST /api/projects/{slug}/packages/sync` | Reconcilia `.venv` com manifesto |
| `GET /api/extensions/catalog` | Catálogo completo (`ExtensionsManager.get_catalog()`) |
| `POST /api/extensions/sync` | Sincroniza com Open VSX |
| `POST /api/extensions/{id}/toggle` | Ativa/desativa |
| `POST /api/extensions/{id}/update` | Atualiza versão registrada (metadado only) |
| `POST /api/extensions/update-all` | Atualiza todas as pendentes |
| `POST /api/extensions/auto-update` | Liga/desliga auto-update |
| `GET /api/extensions/search?q=` | Busca no Open VSX (cacheada) |

Não tem noção de worktree — opera sempre no projeto canônico.

### 3.2 Tool-calling do agente (`agent/tools/packages.py::manage_packages`,
`agent/tools/extensions.py::manage_extensions`)

Descritas ao LLM via `@tool(...)`, chamadas pelo LangGraph em `agent/graph.py` (nó `act`). Cada
uma tem sua função de risco:

```python
# agent/tools/packages.py
_READ_ACTIONS = {"list", "audit"}          # RiskClass.READ — não pausa para aprovação
# install/uninstall/sync/clean            → RiskClass.WRITE — pausa em interrupt()

# agent/tools/extensions.py
_READ_ACTIONS = {"list", "search", "recommend"}  # RiskClass.READ
# toggle/update/update_all/sync                  → RiskClass.WRITE
```

Isso é decidido pela própria ferramenta (`risk=_packages_risk`/`risk=_extensions_risk`, funções
de `args → RiskClass`), nunca pelo chamador — invariante geral do repositório
(`agent/tools/base.py`, ver `CLAUDE.md` raiz).

**Diferença chave em relação à rota REST**: `manage_packages` resolve *worktree → projeto
canônico* (`ctx.project_root`, ou heurística subindo diretórios até achar
`.sicoobito/worktrees/`) antes de agir, porque a sessão do agente frequentemente roda numa
worktree isolada (branch de trabalho) que não tem `.venv`/`requirements.txt` próprios — nesse
caso, empresta o ambiente do projeto canônico via `workspace.git._link_or_share_env()` e sincroniza
`requirements.txt` nos dois lugares quando ambos existem. A rota REST não precisa disso porque
sempre opera no projeto canônico diretamente.

`manage_packages(action="list")` é também o único lugar que seta
`ctx.session_state.packages_checked = True` (fix da task #4 — antes,
`validate_project_runtime()` pré-satisfazia essa flag só por detectar o ecossistema, sem o agente
ter de fato inspecionado as dependências; ver comentário em `agent/runner.py:546`).

`manage_extensions(action="recommend")` cruza o ecossistema detectado do projeto
(`_RECOMMEND_BY_ECOSYSTEM`), marcadores de arquivo (`_RECOMMEND_BY_FILE_MARKER` — ex.
`tailwind.config.js` → sugere a extensão Tailwind) e servidores LSP com extensão correspondente
ainda desativada, para sugerir extensões relevantes sem exigir que o agente adivinhe pelo catálogo
inteiro.

## 4. Frontend — painéis (usuário)

### 4.1 Estrutura de arquivos (task #15 — extração do monólito)

`PackagesPanel.tsx` e `ExtensionsPanel.tsx` viviam embutidos em `components/ide/Panels.tsx`
(~963 linhas somadas). Foram extraídos como arquivos-irmãos no padrão flat já usado por
`AgentPanel.tsx`/`BrowserReplayPanel.tsx` — `components/ide/` não tem convenção de subpastas.
`app/ide/page.tsx` importa os dois do novo local; `Panels.tsx` não referencia mais nenhum dos dois
símbolos.

### 4.2 Confirmação in-app (task #17)

`PackagesPanel`'s uninstall usava `window.confirm()` nativo. Substituído pelo padrão já
estabelecido no projeto: `ConfirmDialog` (`components/ide/Overlays.tsx`), acionado por
`pkgToRemove` guardando o nome do pacote pendente de confirmação; `onConfirm` só dispara
`uninstallProjectPackage` depois do clique em **"confirmar"** no diálogo.

### 4.3 Indicador de sincronização no StatusBar (task #18)

`resolvePackagesSyncStatus(installed, requirementsMap)` (`lib/api/packages.ts`) é uma função pura
compartilhada entre `PackagesPanel` e o novo `PackagesStatusItem` (`StatusBar.tsx`) — os dois
precisam da mesma resposta para "o `.venv` bate com o manifesto?" a partir do mesmo payload de
`getProjectPackages()`. Isso **não** viola a regra de duplicação deliberada entre as fontes de RAG
documentada no `CLAUDE.md` raiz (aquela regra é sobre subsistemas arquiteturais independentes
ficando desacoplados de propósito); aqui é só aritmética pura sobre a mesma forma de dado, então
compartilhar é o certo. Estados possíveis: `"ok"` (instalado bate com manifesto), `"warning"`
(pacote instalado fora do manifesto), `"idle"` (nenhum pacote instalado). Pacotes de bootstrap
(`pip`, `setuptools`, `wheel`, `distribute`) são ignorados na comparação. Clicar no indicador abre
o painel de pacotes (`setPanel("packages")`).

## 5. Frontend — refresh automático entre agente e painel (task #14)

Precedente já existente: o handler SSE do nó `act` em `sessionRuntime.ts` dispara
`sicoobito:browser:open` quando a ferramenta `browser_action` sucede. Estendido no mesmo padrão:

```ts
// components/ide/agent/sessionRuntime.ts — dentro do handler SSE do nó "act"
if (
  (message.name === "manage_packages" || message.name === "manage_extensions") &&
  message.ok !== false
) {
  const eventName = message.name === "manage_packages"
    ? "sicoobito:packages:changed"
    : "sicoobito:extensions:changed";
  window.dispatchEvent(new CustomEvent(eventName, { detail: { sessionId: ... } }));
}
```

`PackagesPanel`, `ExtensionsPanel` e `PackagesStatusItem` cada um registra um listener para o
evento correspondente e rechama sua própria função de fetch. O mesmo evento também é disparado
pelas mutações feitas **pelo próprio usuário** dentro dos painéis (install/uninstall/sync em
`PackagesPanel`) — não só pelo agente — para que o indicador do `StatusBar` não fique
desatualizado quando a mudança vem da UI e não do chat.

Resultado: uma instalação feita pelo agente no chat aparece no painel lateral e no StatusBar sem
o usuário precisar reabrir nada, e vice-versa — as duas superfícies (chat, painel) sempre refletem
o mesmo estado do backend.

## 6. Frontend — card dedicado no chat do agente (task #13)

`manage_packages` tem um card dedicado (`components/ide/agent/cards/PackagesCard.tsx`), roteado
por `ToolCallCard.tsx` (`DEDICATED_CARD_TOOLS` inclui `"manage_packages"`). Como a ferramenta é
uma única tool-call com 6 ações diferentes (ao contrário de `read_file`/`write_file`, que são uma
ferramenta por ação), o card **infere** a ação pelo formato do `data` devolvido — cada
`ToolResult(...)` em `agent/tools/packages.py` tem um shape distinto (`"packages" in data` → list,
`"vulnerabilities" in data` → audit, `"removed_packages" in data` → clean, etc.), já que falhas
zeram `data` e a inferência só roda no caminho de sucesso.

**`manage_extensions` não tem card dedicado** — cai no fallback genérico (texto truncado) por não
estar em `DEDICATED_CARD_TOOLS`. Isso não é uma lacuna descoberta acidentalmente: o escopo da
task #13 era especificamente pacotes; um `ExtensionsCard` equivalente é trabalho futuro caso vire
prioridade, seguindo o mesmo padrão de inferência por shape de `data`.

## 7. Testes

| Camada | Arquivo | Cobre |
| --- | --- | --- |
| Agente — pacotes | `apps/api/tests/test_agent_tools.py` | `manage_packages` (list/install/uninstall/sync/audit/clean) |
| Agente — extensões | `apps/api/tests/test_agent_tools_extensions.py` | `manage_extensions` (list/search/recommend/toggle/update/sync) |
| Backend — extensões | testes de `extensions/manager.py` + `extensions/client.py` (task #9) | hydrate, toggle, sync com marketplace, cache Redis |
| Frontend — painel de pacotes | `apps/web/components/ide/PackagesPanel.test.tsx` | render de lista/vazio/erro, confirmação in-app antes de desinstalar, evento `sicoobito:packages:changed` disparado após install e reagido quando disparado externamente |
| Frontend — painel de extensões | `apps/web/components/ide/ExtensionsPanel.test.tsx` | render de lista, erro+retry (`PanelState`), toggle ativo/inativo, evento `sicoobito:extensions:changed` reagido quando disparado externamente |

Rodar: `cd apps/api && uv run pytest tests/test_agent_tools.py tests/test_agent_tools_extensions.py -q`
e `cd apps/web && bun run typecheck && bun run test`.

## 8. Classes de risco — resumo

| Ferramenta | Ação | `RiskClass` | Precisa aprovação humana? |
| --- | --- | --- | --- |
| `manage_packages` | `list`, `audit` | `READ` | Não |
| `manage_packages` | `install`, `uninstall`, `sync`, `clean` | `WRITE` | Sim (`interrupt()` no `agent/graph.py`) |
| `manage_extensions` | `list`, `search`, `recommend` | `READ` | Não |
| `manage_extensions` | `toggle`, `update`, `update_all`, `sync` | `WRITE` | Sim |

Consistente com o invariante geral do repositório: toda ferramenta declara sua `RiskClass`, e
`WRITE`/`EXEC` sempre param no grafo esperando aprovação — nunca decidido pelo chamador.
