"""Definição e registro de ferramentas do agente.

Cada ferramenta declara uma **classe de risco**, e é ela que decide se o grafo
para para pedir aprovação humana:

- `READ`  lê estado, não muda nada. Executa direto.
- `WRITE` altera arquivo, índice ou repositório. Pede aprovação.
- `EXEC`  roda comando arbitrário. Pede aprovação e só corre no sandbox.

A classificação fica na definição da ferramenta, não no chamador. Se dependesse
de quem chama, bastaria um caminho de código esquecer a checagem para o agente
escrever sem passar por ninguém.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from types import SimpleNamespace
from typing import Any


class RiskClass(StrEnum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"

    @property
    def requires_approval(self) -> bool:
        return self is not RiskClass.READ


# Usados só por `Tool.risk` (catálogo informativo) para sondar o pior caso de
# ferramentas com risco dinâmico, sem precisar de uma sessão real — ver o
# comentário em `Tool.risk`.
_WORST_CASE_ARGS: dict[str, Any] = {"action": "install", "items": [{"content": "x"}]}
_WORST_CASE_CONTEXT = SimpleNamespace(
    mode="plan", session_state=SimpleNamespace(plan_registered=False)
)


@dataclass(slots=True)
class SessionRuntimeState:
    """Estado mutável de execução da sessão de agente.

    Mantém em um lugar explícito as informações que antes ficavam espalhadas em
    atributos de `ToolContext` — isso permite evoluir a sessão sem esconder
    estado implícito em vários campos do contexto.
    """

    current_todos: list[dict[str, Any]] = field(default_factory=list)
    has_unresolved_failure: bool = False
    project_verified: bool = False
    workspace_listed: bool = False
    packages_checked: bool = False
    git_ready: bool = False
    # True depois que a primeira `write_todos` com itens em modo `plan`/
    # `orchestra` foi aprovada e executada nesta sessão (Fase 3 do upgrade
    # do agente) — usado por `agent/tools/plan.py::_todos_risk` para nunca
    # reabrir o gate de aprovação humana nas atualizações seguintes do
    # mesmo plano, mesmo que a lista volte a ficar vazia no meio do caminho.
    plan_registered: bool = False


@dataclass(slots=True)
class ToolContext:
    """O que uma ferramenta pode alcançar. Montado por sessão."""

    session_id: str
    workspace_root: Any  # Path — sem anotar para não importar pathlib no protocolo
    fs: Any  # WorkspaceFS
    project_slug: str = ""
    project_root: Any = None  # Path — raiz canônica do projeto original
    projects_root: Any = None  # Path — raiz que contém todos os projetos
    sandbox: Any | None = None  # Sandbox
    sandboxes: Any | None = None  # SandboxPool (para re-aquisição sob demanda)
    indexer: Any | None = None  # ContextIndexer
    github: Any | None = None  # GitHubClient
    repo_ref: Any | None = None  # RepoRef
    base_branch: str = "main"
    branch: str = ""
    browser: Any | None = None  # BrowserClient
    documents: Any | None = None  # DocumentService
    notes: Any | None = None  # NoteService
    # RetrievalService — pipeline de recuperação (ADR 0019). `None` faz
    # `search_code` cair no `IndexerService.search` de sempre.
    retrieval: Any | None = None
    skills: Any | None = None  # SkillService
    audit: Any | None = None  # AuditService
    firecrawl: Any | None = None  # FirecrawlService
    extensions_manager: Any | None = None  # ExtensionsManager — ver agent/tools/extensions.py
    security: Any | None = None  # SecureBertService
    trace_recorder: Any | None = None  # TraceRecorder
    # RouterEngine — ferramentas que fazem uma segunda chamada de LLM isolada
    # da conversa principal (ex. request_code_review) usam isto.
    engine: Any | None = None
    # Conteúdo de `.eltanix/instructions.md` no projeto (não no worktree da
    # sessão) — texto livre que o usuário escreveu na aba "Instruções" do
    # popover, concatenado ao SYSTEM_PROMPT em `agent/graph.py::think()`.
    custom_instructions: str | None = None
    # Especialização deste agente (Horizonte 4, item 3 da auditoria
    # arquitetural) — `system_prompt` de uma Skill existente, escolhida pelo
    # pai ao chamar `spawn_agent(skill_name=...)`, concatenado ao SYSTEM_PROMPT
    # em `agent/graph.py::think()`. `None` para toda sessão raiz e todo filho
    # spawnado sem `skill_name` — não muda o comportamento de hoje.
    specialization_prompt: str | None = None
    # Skills roteadas automaticamente por similaridade de embedding
    # (`SkillService.find_relevant`, chamado em `AgentRunner.create_session()`)
    # ou forçadas por um slash command reconhecido — terceira seção opcional
    # do system prompt, mesmo mecanismo aditivo de `custom_instructions`/
    # `specialization_prompt` em `agent/graph.py::build_graph()`. `None`
    # quando nenhuma skill bateu o `min_score` ou o roteamento falhou
    # (degrada silenciosamente, nunca bloqueia a sessão).
    routed_skills_prompt: str | None = None
    # Regras de contexto por glob (Fase 4 do upgrade do agente, estilo
    # `.cursor/rules`) já casadas contra `focus_files`/`focus_folder` e
    # renderizadas em texto por `agent/context_rules.py::build_context_rules_prompt`
    # — quarta seção opcional do system prompt, mesmo mecanismo aditivo das
    # três anteriores. `None` quando nenhuma regra casou ou o projeto não
    # tem `.eltanix/context_rules.yaml`.
    context_rules_prompt: str | None = None
    # Modo customizado (Fase 6 do upgrade do agente) resolvido uma única vez
    # na criação da sessão (`AgentRunner._resolve_custom_mode`), quando `mode`
    # não é um dos 7 modos embutidos (`agent/state.py::BUILTIN_MODES`).
    # `allowed_tools=None` significa "não resolvido" (id inválido, modo
    # deletado, ou sem `CustomModeService`) — `agent/graph.py::_tool_schemas`
    # degrada para somente leitura nesse caso, nunca libera WRITE/EXEC.
    # `allowed_tools=[]` é uma lista vazia *de verdade* salva pelo usuário —
    # nenhuma ferramenta liberada, também nunca escrita.
    custom_mode_allowed_tools: list[str] | None = None
    custom_mode_prompt_block: str | None = None
    # Modo escolhido na criação da sessão (`AgentSession.mode`) — fixo pelo
    # resto da sessão (não há troca de modo em runtime hoje). Ferramentas
    # cuja classe de risco depende de contexto além dos próprios argumentos
    # (ex: `write_todos` só vira WRITE na primeira chamada em modo
    # `plan`/`orchestra`, ver `agent/tools/plan.py::_todos_risk`) leem daqui
    # em vez de receberem o modo por parâmetro.
    mode: str = "agent"
    # Política de auto-aprovação (`agent/approval_policy.py::ApprovalPolicy`)
    # carregada de `.eltanix/approval_policy.yaml` no projeto — consultada
    # pelo nó `approve` em `agent/graph.py` antes do `interrupt()`. `None`
    # equivale a uma política vazia (nenhuma regra, tudo pausa como sempre).
    approval_policy: Any | None = None
    # Snapshots de arquivo antes de cada escrita (Fase 8 do upgrade do
    # agente: checkpoints/rewind) — gravado best-effort em `agent/graph.py::
    # act()`, nunca bloqueia a ferramenta em si (mesmo espírito de `audit`/
    # `trace_recorder`: `None` degrada para "sem rewind disponível", não erro).
    snapshots: Any | None = None  # SnapshotService
    # Orquestração multiagente (ver ADR 0004) — usados por
    # `agent/tools/agents_graph.py`. `coordinator` é `None` sem Redis
    # configurado (orquestração indisponível, `spawn_agent` falha fechado).
    coordinator: Any | None = None  # AgentCoordinator
    # Fechamento `async (*, task: str, display_name: str) -> str` (devolve o
    # session_id do filho) montado em `AgentRunner.create_session()` — mesmo
    # padrão de callback injetado que o próprio Strix usa pro seu
    # `create_agent`, pra `ToolContext` não precisar segurar uma referência
    # circular ao `AgentRunner` inteiro. `None` quando não há coordenador.
    spawn_child_agent: Any | None = None
    # Fechamento `async (target_session_id: str) -> bool` — dispara um burst
    # headless novo pra um agente já existente que não está sendo dirigido
    # por ninguém no momento (usado por `send_message_to_agent` pra acordar o
    # alvo depois de enfileirar a mensagem). Devolve `False` sem fazer nada
    # se o alvo já está sendo dirigido, foi parado, ou é desconhecido — quem
    # chama não precisa (nem deve) tratar isso como erro.
    wake_agent: Any | None = None
    parent_session_id: str | None = None
    max_wait_seconds: float = 300.0
    max_spawn_depth: int = 3
    max_children_per_agent: int = 4
    # Callback assíncrono para streaming em tempo real de micro-atividades
    # (ex: início/fim de tool, thinking)
    on_activity: Any | None = None
    session_state: SessionRuntimeState = field(default_factory=SessionRuntimeState)

    @property
    def current_todos(self) -> list[dict[str, Any]]:
        return self.session_state.current_todos

    @current_todos.setter
    def current_todos(self, value: list[dict[str, Any]]) -> None:
        self.session_state.current_todos = value

    @property
    def has_unresolved_failure(self) -> bool:
        return self.session_state.has_unresolved_failure

    @has_unresolved_failure.setter
    def has_unresolved_failure(self, value: bool) -> None:
        self.session_state.has_unresolved_failure = value


@dataclass(slots=True)
class ToolResult:
    ok: bool
    content: str
    # Dados estruturados para a UI (diff para o Monaco, lista de arquivos...).
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(cls, message: str) -> ToolResult:
        # Erro volta como resultado, não como exceção: o modelo precisa ler o
        # que deu errado para corrigir a próxima tentativa.
        return cls(ok=False, content=f"ERRO: {message}")


class Tool:
    name: str
    description: str
    # O callable recebe `(argumentos, context)` — `context` é `None` nos
    # pontos que só olham o "pior caso" sem sessão real (listagem de
    # ferramentas, filtro de schema por modo em `_tool_schemas`). Toda
    # função de risco precisa aceitar o segundo parâmetro mesmo que o
    # ignore (ver `_packages_risk`/`_extensions_risk`), para que ferramentas
    # como `write_todos` possam decidir com base em estado de sessão
    # (`ToolContext.mode`/`session_state`) sem um tipo paralelo.
    _risk: RiskClass | Callable[[dict[str, Any], ToolContext | None], RiskClass]
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]
    summarize: Callable[[dict[str, Any]], str] | None = None
    status_from_result: Callable[[ToolResult], str] | None = None

    def __init__(
        self,
        name: str,
        description: str,
        risk: RiskClass | Callable[[dict[str, Any], ToolContext | None], RiskClass],
        parameters: dict[str, Any],
        handler: Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]],
        summarize: Callable[[dict[str, Any]], str] | None = None,
        status_from_result: Callable[[ToolResult], str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self._risk = risk
        self.parameters = parameters
        self.handler = handler
        self.summarize = summarize
        # Override opcional pra telemetria (`agent/graph.py::_telemetry_status`):
        # ferramentas cujo `ToolResult.ok` não reflete sucesso real (ex.
        # `run_command`, que sempre devolve `ok=True` de propósito — o modelo
        # precisa ver comando que falhou, não ferramenta que falhou) declaram
        # aqui como derivar o status real a partir de `data`, em vez de
        # `_telemetry_status` precisar de um `if nome == "...":` por ferramenta.
        self.status_from_result = status_from_result

    @property
    def risk(self) -> RiskClass:
        # Cenário-pior-caso genérico para o catálogo informativo
        # (`GET /api/agent/tools`): cobre tanto risco por argumento
        # (`_packages_risk`/`_extensions_risk`, olham `action`) quanto risco
        # dependente de sessão (`_todos_risk`, olha `context.mode`/
        # `session_state.plan_registered`) — sem isso, `write_todos` sempre
        # relatava `read`/`requires_approval: false` no catálogo mesmo
        # podendo virar `write` de verdade em modo `plan`/`orchestra`.
        if callable(self._risk):
            return self._risk(
                _WORST_CASE_ARGS,
                _WORST_CASE_CONTEXT,  # type: ignore[arg-type]
            )
        return self._risk

    def resolve_risk(
        self, arguments: dict[str, Any] | None = None, context: ToolContext | None = None
    ) -> RiskClass:
        if callable(self._risk):
            return self._risk(arguments or {}, context)
        return self._risk

    @property
    def base_risk(self) -> RiskClass:
        return self.resolve_risk({})

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def describe_call(self, arguments: dict[str, Any]) -> str:
        if self.summarize is not None:
            return self.summarize(arguments)
        return f"{self.name}({', '.join(f'{k}={v!r}' for k, v in arguments.items())})"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"ferramenta duplicada: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def unregister(self, name: str) -> None:
        """Desfaz um `register()` em runtime — usado pelo `MCPManager` ao
        recarregar servidores (reconectar/editar/remover sem reiniciar a API).
        Ferramentas estáticas (`@tool`) nunca precisam disto."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def by_risk(self, risk: RiskClass) -> list[Tool]:
        return [t for t in self._tools.values() if t.base_risk is risk]

    def schemas(self, *, allow_exec: bool = True, allow_write: bool = True) -> list[dict[str, Any]]:
        """Schemas para o modelo.

        Modos mais restritos (Ask, Edit) simplesmente não recebem as ferramentas
        que não podem usar — é mais confiável que instruir o modelo a não
        chamá-las.
        """
        tools = []
        for tool in self._tools.values():
            risk = tool.base_risk
            if risk is RiskClass.EXEC and not allow_exec:
                continue
            if risk is RiskClass.WRITE and not allow_write:
                continue
            tools.append(tool.to_openai_schema())
        return tools


registry = ToolRegistry()


def tool(
    *,
    name: str,
    description: str,
    risk: RiskClass | Callable[[dict[str, Any], ToolContext | None], RiskClass],
    parameters: dict[str, Any],
    summarize: Callable[[dict[str, Any]], str] | None = None,
    status_from_result: Callable[[ToolResult], str] | None = None,
):
    """Decorador de registro."""

    def wrapper(
        handler: Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]],
    ) -> Tool:
        return registry.register(
            Tool(
                name=name,
                description=description,
                risk=risk,
                parameters=parameters,
                handler=handler,
                summarize=summarize,
                status_from_result=status_from_result,
            )
        )

    return wrapper
