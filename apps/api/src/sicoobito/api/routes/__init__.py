from sicoobito.api.routes.agent import router as agent_router
from sicoobito.api.routes.audit import router as audit_router
from sicoobito.api.routes.auth import router as auth_router
from sicoobito.api.routes.context import router as context_router
from sicoobito.api.routes.documents import router as documents_router
from sicoobito.api.routes.git import router as git_router
from sicoobito.api.routes.health import router as health_router
from sicoobito.api.routes.lsp import router as lsp_router
from sicoobito.api.routes.lsp import ws_router as lsp_ws_router
from sicoobito.api.routes.mcp import router as mcp_router
from sicoobito.api.routes.metrics import router as metrics_router
from sicoobito.api.routes.notes import router as notes_router
from sicoobito.api.routes.projects import router as projects_router
from sicoobito.api.routes.skills import router as skills_router
from sicoobito.api.routes.telemetry import router as telemetry_router
from sicoobito.api.routes.workspace import router as workspace_router
from sicoobito.api.routes.workspace import ws_router as workspace_ws_router
from sicoobito.graphify.api.router import router as graphify_router

__all__ = [
    "agent_router",
    "audit_router",
    "auth_router",
    "context_router",
    "documents_router",
    "git_router",
    "graphify_router",
    "health_router",
    "lsp_router",
    "lsp_ws_router",
    "mcp_router",
    "metrics_router",
    "notes_router",
    "projects_router",
    "skills_router",
    "telemetry_router",
    "workspace_router",
    "workspace_ws_router",
]
