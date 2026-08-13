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
from typing import Any


class RiskClass(StrEnum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"

    @property
    def requires_approval(self) -> bool:
        return self is not RiskClass.READ


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


@dataclass(slots=True)
class ToolContext:
    """O que uma ferramenta pode alcançar. Montado por sessão."""

    session_id: str
    workspace_root: Any  # Path — sem anotar para não importar pathlib no protocolo
    fs: Any  # WorkspaceFS
    project_slug: str = ""
    projects_root: Any = None  # Path — raiz que contém todos os projetos
    sandbox: Any | None = None  # Sandbox
    indexer: Any | None = None  # ContextIndexer
    github: Any | None = None  # GitHubClient
    repo_ref: Any | None = None  # RepoRef
    base_branch: str = "main"
    branch: str = ""
    browser: Any | None = None  # BrowserClient
    documents: Any | None = None  # DocumentService
    notes: Any | None = None  # NoteService
    skills: Any | None = None  # SkillService
    audit: Any | None = None  # AuditService
    security: Any | None = None  # SecureBertService
    trace_recorder: Any | None = None  # TraceRecorder
    # RouterEngine — ferramentas que fazem uma segunda chamada de LLM isolada
    # da conversa principal (ex. request_code_review) usam isto.
    engine: Any | None = None
    # Conteúdo de `.sicoobito/instructions.md` no projeto (não no worktree da
    # sessão) — texto livre que o usuário escreveu na aba "Instruções" do
    # popover, concatenado ao SYSTEM_PROMPT em `agent/graph.py::think()`.
    custom_instructions: str | None = None
    # Política de auto-aprovação (`agent/approval_policy.py::ApprovalPolicy`)
    # carregada de `.sicoobito/approval_policy.yaml` no projeto — consultada
    # pelo nó `approve` em `agent/graph.py` antes do `interrupt()`. `None`
    # equivale a uma política vazia (nenhuma regra, tudo pausa como sempre).
    approval_policy: Any | None = None
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


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    risk: RiskClass
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]
    # Resumo curto mostrado no pedido de aprovação, no lugar do JSON cru.
    summarize: Callable[[dict[str, Any]], str] | None = None

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
        return [t for t in self._tools.values() if t.risk is risk]

    def schemas(self, *, allow_exec: bool = True, allow_write: bool = True) -> list[dict[str, Any]]:
        """Schemas para o modelo.

        Modos mais restritos (Ask, Edit) simplesmente não recebem as ferramentas
        que não podem usar — é mais confiável que instruir o modelo a não
        chamá-las.
        """
        tools = []
        for tool in self._tools.values():
            if tool.risk is RiskClass.EXEC and not allow_exec:
                continue
            if tool.risk is RiskClass.WRITE and not allow_write:
                continue
            tools.append(tool.to_openai_schema())
        return tools


registry = ToolRegistry()


def tool(
    *,
    name: str,
    description: str,
    risk: RiskClass,
    parameters: dict[str, Any],
    summarize: Callable[[dict[str, Any]], str] | None = None,
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
            )
        )

    return wrapper
