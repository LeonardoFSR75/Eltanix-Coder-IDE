"""Mapeia CVEs de dependências para a linha do manifesto onde o pacote é
declarado — a fonte das gutters de CVE do editor (Onda 1.5).

O scan em si já existe (`packages/commands.py::run_dependency_audit`, via
`pip-audit` / `npm audit`); aqui é só a parte pura: casar cada pacote
vulnerável com a linha de `requirements.txt` / `package.json` que o declara,
para o Monaco pôr um marcador na gutter.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_MANIFESTS = {"requirements.txt", "package.json"}

_SEVERITY_RANK = {"critical": 4, "high": 3, "moderate": 2, "medium": 2, "low": 1, "unknown": 0}

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9._-]+)")


@dataclass(slots=True)
class DependencyMarker:
    line: int
    package: str
    severity: str
    ids: list[str]
    fix: str | None
    summary: str


def is_manifest(rel_path: str) -> bool:
    return rel_path.replace("\\", "/").rsplit("/", 1)[-1] in _MANIFESTS


def _canon(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def markers_from_audit(
    manifest_name: str, manifest_text: str, audit: dict[str, Any]
) -> list[DependencyMarker]:
    """`audit` é o dict devolvido por `run_dependency_audit`. Formato das vulns
    varia por ecossistema (pip-audit vs npm audit) — os dois são normalizados
    aqui."""
    vulns = audit.get("vulnerabilities") or []
    if not vulns:
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for v in vulns:
        pkg = _canon(str(v.get("package") or ""))
        if pkg:
            grouped.setdefault(pkg, []).append(v)
    if not grouped:
        return []

    base = manifest_name.replace("\\", "/").rsplit("/", 1)[-1]
    if base == "requirements.txt":
        line_of = _requirements_lines(manifest_text)
    elif base == "package.json":
        line_of = _package_json_lines(manifest_text)
    else:
        return []

    markers: list[DependencyMarker] = []
    for pkg, entries in grouped.items():
        line = line_of.get(pkg)
        if line is None:
            continue
        markers.append(_merge(pkg, line, entries))
    markers.sort(key=lambda m: m.line)
    return markers


def _merge(pkg: str, line: int, entries: list[dict[str, Any]]) -> DependencyMarker:
    ids: list[str] = []
    fixes: list[str] = []
    severity = "unknown"
    for e in entries:
        vid = e.get("id") or e.get("cve")
        if vid and vid not in ids:
            ids.append(str(vid))
        sev = str(e.get("severity") or "").lower()
        if _SEVERITY_RANK.get(sev, -1) > _SEVERITY_RANK.get(severity, -1):
            severity = sev
        for fv in e.get("fix_versions", []) or []:
            if fv and fv not in fixes:
                fixes.append(str(fv))
        if e.get("fix_available") and not fixes:
            fixes.append("disponível")

    descr = ""
    for e in entries:
        descr = (e.get("description") or e.get("range") or "").strip()
        if descr:
            break

    count = len(ids) or len(entries)
    summary = f"{pkg}: {count} vulnerabilidade(s) conhecida(s)"
    if descr:
        summary += f" — {descr[:200]}"
    return DependencyMarker(
        line=line,
        package=pkg,
        severity=severity if severity in _SEVERITY_RANK else "unknown",
        ids=ids,
        fix=", ".join(fixes) or None,
        summary=summary,
    )


def _requirements_lines(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "-r", "--")):
            continue
        m = _REQ_NAME.match(line)
        if m:
            out.setdefault(_canon(m.group(1)), i)
    return out


def _package_json_lines(text: str) -> dict[str, int]:
    """Linha de cada dependência. Tenta o parse estruturado (para saber quais
    chaves são de fato dependências) e volta a localizar cada nome no texto
    cru para achar o número da linha."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        data = {}

    names: set[str] = set()
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        block = data.get(section) if isinstance(data, dict) else None
        if isinstance(block, dict):
            names.update(block.keys())

    lines = text.splitlines()
    out: dict[str, int] = {}
    if names:
        for name in names:
            pat = re.compile(rf'^\s*"{re.escape(name)}"\s*:')
            for i, raw in enumerate(lines, start=1):
                if pat.match(raw):
                    out[_canon(name)] = i
                    break
        return out

    # Sem parse: heurística — qualquer par `"nome": "^1.2.3"`.
    dep_like = re.compile(r'^\s*"([A-Za-z0-9._@/-]+)"\s*:\s*"[^"]*"\s*,?\s*$')
    for i, raw in enumerate(lines, start=1):
        m = dep_like.match(raw)
        if m:
            out.setdefault(_canon(m.group(1)), i)
    return out
