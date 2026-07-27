from sicoobito.api.routes.agent import router as agent_router
from sicoobito.api.routes.context import router as context_router
from sicoobito.api.routes.git import router as git_router
from sicoobito.api.routes.health import router as health_router
from sicoobito.api.routes.lsp import router as lsp_router
from sicoobito.api.routes.lsp import ws_router as lsp_ws_router
from sicoobito.api.routes.metrics import router as metrics_router
from sicoobito.api.routes.workspace import projects_router
from sicoobito.api.routes.workspace import router as workspace_router
from sicoobito.api.routes.workspace import ws_router as workspace_ws_router

__all__ = [
    "agent_router",
    "context_router",
    "git_router",
    "health_router",
    "lsp_router",
    "lsp_ws_router",
    "metrics_router",
    "projects_router",
    "workspace_router",
    "workspace_ws_router",
]
