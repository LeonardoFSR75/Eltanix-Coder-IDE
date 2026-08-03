"""Registro das ferramentas do agente.

Os módulos são importados pelo efeito colateral do decorador `@tool`, que
registra cada ferramenta em `registry`.
"""

from sicoobito.agent.tools import (  # noqa: F401
    browser,
    documents,
    files,
    notes,
    plan,
    review,
    shell,
    skills,
    vcs,
)
from sicoobito.agent.tools.base import (
    RiskClass,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    registry,
)

__all__ = [
    "RiskClass",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "registry",
]
