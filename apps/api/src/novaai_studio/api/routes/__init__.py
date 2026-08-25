from novaai_studio.api.routes.agent import router as agent_router
from novaai_studio.api.routes.analytics import router as analytics_router
from novaai_studio.api.routes.approval_policy import router as approval_policy_router
from novaai_studio.api.routes.audit import router as audit_router
from novaai_studio.api.routes.auth import router as auth_router
from novaai_studio.api.routes.browser import router as browser_router
from novaai_studio.api.routes.browser import ws_router as browser_ws_router
from novaai_studio.api.routes.containers import router as containers_router
from novaai_studio.api.routes.context import router as context_router
from novaai_studio.api.routes.context_rules import router as context_rules_router
from novaai_studio.api.routes.custom_modes import router as custom_modes_router
from novaai_studio.api.routes.documents import router as documents_router
from novaai_studio.api.routes.extensions import router as extensions_router
from novaai_studio.api.routes.firecrawl import router as firecrawl_router
from novaai_studio.api.routes.git import router as git_router
from novaai_studio.api.routes.health import router as health_router
from novaai_studio.api.routes.lsp import router as lsp_router
from novaai_studio.api.routes.lsp import ws_router as lsp_ws_router
from novaai_studio.api.routes.mcp import router as mcp_router
from novaai_studio.api.routes.metrics import router as metrics_router
from novaai_studio.api.routes.notes import router as notes_router
from novaai_studio.api.routes.packages import router as packages_router
from novaai_studio.api.routes.projects import router as projects_router
from novaai_studio.api.routes.security import router as security_router
from novaai_studio.api.routes.skills import router as skills_router
from novaai_studio.api.routes.telemetry import router as telemetry_router
from novaai_studio.api.routes.trello import router as trello_router
from novaai_studio.api.routes.workspace import router as workspace_router
from novaai_studio.api.routes.workspace import ws_router as workspace_ws_router
from novaai_studio.graphify.api.router import router as graphify_router

__all__ = [
    "agent_router",
    "analytics_router",
    "approval_policy_router",
    "audit_router",
    "auth_router",
    "browser_router",
    "browser_ws_router",
    "containers_router",
    "context_router",
    "context_rules_router",
    "custom_modes_router",
    "documents_router",
    "extensions_router",
    "firecrawl_router",
    "git_router",
    "graphify_router",
    "health_router",
    "lsp_router",
    "lsp_ws_router",
    "mcp_router",
    "metrics_router",
    "notes_router",
    "packages_router",
    "projects_router",
    "security_router",
    "skills_router",
    "telemetry_router",
    "trello_router",
    "workspace_router",
    "workspace_ws_router",
]
