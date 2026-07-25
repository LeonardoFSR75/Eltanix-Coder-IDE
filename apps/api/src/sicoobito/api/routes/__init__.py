from sicoobito.api.routes.agent import router as agent_router
from sicoobito.api.routes.context import router as context_router
from sicoobito.api.routes.health import router as health_router
from sicoobito.api.routes.metrics import router as metrics_router
from sicoobito.api.routes.workspace import router as workspace_router

__all__ = [
    "agent_router",
    "context_router",
    "health_router",
    "metrics_router",
    "workspace_router",
]
