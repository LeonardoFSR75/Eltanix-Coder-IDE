"""Registro das ferramentas do agente.

Os módulos são importados pelo efeito colateral do decorador `@tool`, que
registra cada ferramenta em `registry`.
"""

from eltanix.agent.tools import (  # noqa: F401
    agents_graph,
    browser,
    documents,
    extensions,
    files,
    firecrawl,
    graph,
    graphify,
    notes,
    packages,
    plan,
    project_manager,
    review,
    security,
    shell,
    skills,
    trello,
    vcs,
)
from eltanix.agent.tools.base import (
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
