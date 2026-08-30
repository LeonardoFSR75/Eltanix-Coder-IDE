"""Rotas de "gutter intelligence" do editor (Onda 1.5).

Alimentam as decorações de margem do Monaco:

- `GET /api/quality/coverage` — linhas cobertas / descobertas / parciais de um
  arquivo, lidas de um relatório de cobertura já gerado no projeto.
- `GET /api/quality/dependency-markers` — CVEs conhecidas por linha de um
  manifesto (`requirements.txt` / `package.json`), via o scan que já existe em
  `packages/commands.py`.

Ambas são READ-only e degradam para `204`/lista vazia quando não há dado —
gutters são decorativas, nunca podem quebrar a abertura de um arquivo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status

from eltanix.api.deps import AuthDep, SettingsDep
from eltanix.api.routes.packages import (
    detect_ecosystem,
    get_python_executable,
    get_venv_path,
)
from eltanix.api.routes.workspace import project_fs
from eltanix.auth.rbac import require_role_by_slug
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.packages.commands import run_dependency_audit
from eltanix.workspace.coverage import load_project_coverage
from eltanix.workspace.dependency_markers import is_manifest, markers_from_audit

log = get_logger(__name__)

router = APIRouter(prefix="/api/quality", tags=["quality"], dependencies=[AuthDep])


async def _check_project_access(request: Request, project: str, min_role: str) -> None:
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=project, min_role=min_role)


_DEP_CACHE_PREFIX = "quality:depmarkers"
_DEP_CACHE_TTL_SECONDS = 600
_DEP_AUDIT_TIMEOUT_S = 25.0


@router.get("/coverage")
async def coverage(
    request: Request,
    settings: SettingsDep,
    project: str = Query(min_length=1),
    path: str = Query(min_length=1),
) -> Any:
    """Cobertura de um arquivo. `204` quando não há relatório no projeto, ou
    quando há relatório mas ele não menciona este arquivo."""
    fs = project_fs(settings, project)
    try:
        rel_path = fs.relative(fs.resolve(path))
    except Exception:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await _check_project_access(request, project, min_role="viewer")

    data = await asyncio.to_thread(load_project_coverage, fs.root)
    if data is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    fc = data.file(rel_path)
    if fc is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return {
        "path": rel_path,
        "format": data.fmt,
        "source": data.source,
        "generated_at": data.generated_at,
        "project_line_rate": round(data.line_rate, 4),
        "file": {
            "covered": fc.covered,
            "uncovered": fc.uncovered,
            "partial": fc.partial,
            "line_rate": round(fc.line_rate, 4),
        },
    }


@router.get("/dependency-markers")
async def dependency_markers(
    request: Request,
    settings: SettingsDep,
    project: str = Query(min_length=1),
    path: str = Query(min_length=1),
) -> Any:
    """CVEs por linha de um manifesto de dependências. Lista vazia (não `204`)
    quando o arquivo não é um manifesto ou o scanner não está disponível — o
    cliente distingue "sem marcador" de "sem suporte" pelo campo
    `tool_available`."""
    fs = project_fs(settings, project)
    try:
        rel_path = fs.relative(fs.resolve(path))
    except Exception:
        return {"markers": [], "supported": False}

    if not is_manifest(rel_path):
        return {"markers": [], "supported": False}

    await _check_project_access(request, project, min_role="viewer")

    try:
        manifest_text = fs.read(rel_path)
    except Exception:
        return {"markers": [], "supported": False}

    digest = hashlib.sha1(manifest_text.encode("utf-8", errors="ignore")).hexdigest()
    cache_key = f"{_DEP_CACHE_PREFIX}:{fs.root.as_posix()}:{rel_path}:{digest}"
    redis = getattr(request.app.state, "redis", None)

    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            log.warning("quality.depmarkers.cache_unavailable", error=str(exc))

    eco = detect_ecosystem(fs.root)
    py_exe = get_python_executable(get_venv_path(fs.root))
    try:
        audit = await asyncio.wait_for(
            run_dependency_audit(eco, fs.root, py_exe), timeout=_DEP_AUDIT_TIMEOUT_S
        )
    except Exception as exc:
        log.warning("quality.depmarkers.audit_failed", error=str(exc)[:200])
        return {"markers": [], "supported": True, "tool_available": False}

    markers = markers_from_audit(rel_path, manifest_text, audit)
    result = {
        "path": rel_path,
        "ecosystem": eco,
        "tool": audit.get("tool"),
        "tool_available": bool(audit.get("tool_available", True)),
        "supported": bool(audit.get("supported", False)),
        "scanned_at": time.time(),
        "markers": [
            {
                "line": m.line,
                "package": m.package,
                "severity": m.severity,
                "ids": m.ids,
                "fix": m.fix,
                "summary": m.summary,
            }
            for m in markers
        ],
    }

    if redis is not None:
        try:
            await redis.set(cache_key, json.dumps(result), ex=_DEP_CACHE_TTL_SECONDS)
        except Exception as exc:
            log.warning("quality.depmarkers.cache_unavailable", error=str(exc))

    return result
