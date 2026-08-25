from eltanix.api.routes.agent import router as agent_router
from eltanix.api.routes.analytics import router as analytics_router
from eltanix.api.routes.approval_policy import router as approval_policy_router
from eltanix.api.routes.audit import router as audit_router
from eltanix.api.routes.auth import router as auth_router
from eltanix.api.routes.browser import router as browser_router
from eltanix.api.routes.browser import ws_router as browser_ws_router
from eltanix.api.routes.containers import router as containers_router
from eltanix.api.routes.context import router as context_router
from eltanix.api.routes.context_rules import router as context_rules_router
from eltanix.api.routes.custom_modes import router as custom_modes_router
from eltanix.api.routes.documents import router as documents_router
from eltanix.api.routes.extensions import router as extensions_router
from eltanix.api.routes.firecrawl import router as firecrawl_router
from eltanix.api.routes.git import router as git_router
from eltanix.api.routes.health import router as health_router
from eltanix.api.routes.lsp import router as lsp_router
from eltanix.api.routes.lsp import ws_router as lsp_ws_router
from eltanix.api.routes.mcp import router as mcp_router
from eltanix.api.routes.metrics import router as metrics_router
from eltanix.api.routes.notes import router as notes_router
from eltanix.api.routes.packages import router as packages_router
from eltanix.api.routes.projects import router as projects_router
from eltanix.api.routes.security import router as security_router
from eltanix.api.routes.skills import router as skills_router
from eltanix.api.routes.telemetry import router as telemetry_router
from eltanix.api.routes.trello import router as trello_router
from eltanix.api.routes.workspace import router as workspace_router
from eltanix.api.routes.workspace import ws_router as workspace_ws_router
from eltanix.graphify.api.router import router as graphify_router

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
