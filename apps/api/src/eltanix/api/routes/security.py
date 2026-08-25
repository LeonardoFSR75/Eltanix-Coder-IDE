"""Rota de segurança para análise de texto e prompts usando SecureBERT2."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from eltanix.api.deps import AuthDep
from eltanix.audit.service import AuditService
from eltanix.security.service import SecureBertService

router = APIRouter(prefix="/api/security", tags=["security"], dependencies=[AuthDep])
_service = SecureBertService()


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


class SecureBertAnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)


@router.get("/securebert/health")
async def securebert_health(request: Request) -> dict[str, Any]:
    result = _service.health()
    audit = _audit(request)
    if audit is not None:
        try:
            await audit.record(
                actor="api",
                module="Security",
                action="Health check do SecureBERT",
                details=f"available={result.get('available')} mode={result.get('mode')}",
                risk_level="low",
                status="success",
                metadata={"provider": result.get("provider"), "version": result.get("version")},
            )
        except Exception:
            pass
    return result


@router.post("/securebert/analyze")
async def securebert_analyze(payload: SecureBertAnalyzeRequest, request: Request) -> dict[str, Any]:
    result = _service.analyze(payload.text)
    audit = _audit(request)
    if audit is not None:
        try:
            await audit.record(
                actor="api",
                module="Security",
                action="Análise de texto com SecureBERT",
                details=(
                    f"classification={result.get('classification')} score={result.get('score')}"
                ),
                risk_level=(
                    "medium" if result.get("classification") in {"suspicious", "unsafe"} else "low"
                ),
                status="success",
                metadata={
                    "provider": result.get("provider"),
                    "available": result.get("available"),
                    "mode": result.get("mode"),
                    "reasons": result.get("reasons", []),
                    "length": len(payload.text),
                },
            )
        except Exception:
            pass
    return result
