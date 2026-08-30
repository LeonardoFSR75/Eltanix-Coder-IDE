"""Leitura de relatórios de cobertura de teste para as gutters do editor (Onda 1.5).

Puro e sem I/O de rede: dado o root de um projeto, procura um relatório de
cobertura já gerado (o IDE não roda os testes por conta própria) e devolve, por
arquivo, quais linhas estão cobertas / descobertas / parcialmente cobertas.

Três formatos, os que as ferramentas de teste ubíquas emitem sem plugin extra:

- **Cobertura XML** (`coverage.xml`) — `pytest --cov --cov-report=xml`, e o padrão
  de fato para JVM/Cobertura/gcovr.
- **LCOV** (`lcov.info`) — `nyc`, `c8`, `vitest --coverage`, `cargo-llvm-cov`, gcov.
- **Istanbul JSON** (`coverage/coverage-final.json`) — Jest / Istanbul cru.

Qualquer arquivo malformado é ignorado em silêncio (a feature é decorativa; um
relatório quebrado não pode derrubar a rota do editor).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# Onde procurar, em ordem de preferência. Só o root e um nível de `coverage/` —
# não varremos a árvore inteira (node_modules, .venv, worktrees do agente...).
_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("coverage.xml", "cobertura"),
    ("cobertura.xml", "cobertura"),
    ("coverage/cobertura-coverage.xml", "cobertura"),
    ("coverage/coverage.xml", "cobertura"),
    ("lcov.info", "lcov"),
    ("coverage/lcov.info", "lcov"),
    ("coverage/lcov/lcov.info", "lcov"),
    ("coverage/coverage-final.json", "istanbul"),
    ("coverage-final.json", "istanbul"),
)

_MAX_REPORT_BYTES = 25 * 1024 * 1024


@dataclass(slots=True)
class FileCoverage:
    path: str
    covered: list[int] = field(default_factory=list)
    uncovered: list[int] = field(default_factory=list)
    partial: list[int] = field(default_factory=list)

    @property
    def line_rate(self) -> float:
        total = len(self.covered) + len(self.uncovered) + len(self.partial)
        if not total:
            return 0.0
        # Parcial conta como meia linha — reflete melhor a realidade de branch.
        return (len(self.covered) + 0.5 * len(self.partial)) / total


@dataclass(slots=True)
class ProjectCoverage:
    fmt: str
    source: str
    generated_at: float | None
    files: dict[str, FileCoverage]

    @property
    def line_rate(self) -> float:
        cov = sum(len(f.covered) for f in self.files.values())
        part = sum(len(f.partial) for f in self.files.values())
        unc = sum(len(f.uncovered) for f in self.files.values())
        total = cov + part + unc
        return (cov + 0.5 * part) / total if total else 0.0

    def file(self, rel_path: str) -> FileCoverage | None:
        """Casa o caminho pedido (relativo ao projeto, POSIX) com uma entrada do
        relatório, tolerando prefixos de raiz diferentes entre quem gerou o
        relatório e o nosso `PROJECTS_ROOT`."""
        want = _norm(rel_path)
        direct = self.files.get(want)
        if direct is not None:
            return direct
        # Sufixo: `src/pkg/mod.py` casa `/abs/ci/checkout/src/pkg/mod.py`.
        want_parts = want.split("/")
        best: FileCoverage | None = None
        best_overlap = 0
        for key, fc in self.files.items():
            kp = key.split("/")
            overlap = _suffix_overlap(want_parts, kp)
            if overlap > best_overlap and overlap >= min(2, len(want_parts)):
                best, best_overlap = fc, overlap
        return best


def _norm(p: str) -> str:
    p = p.replace("\\", "/").lstrip("./")
    while p.startswith("../"):
        p = p[3:]
    return p


def _suffix_overlap(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(reversed(a), reversed(b), strict=False):
        if x != y:
            break
        n += 1
    return n


def load_project_coverage(root: Path) -> ProjectCoverage | None:
    for rel, fmt in _CANDIDATES:
        candidate = root / rel
        try:
            if not candidate.is_file() or candidate.stat().st_size > _MAX_REPORT_BYTES:
                continue
            raw = candidate.read_text(encoding="utf-8", errors="ignore")
            mtime = candidate.stat().st_mtime
        except OSError:
            continue

        try:
            if fmt == "cobertura":
                files = _parse_cobertura(raw)
            elif fmt == "lcov":
                files = _parse_lcov(raw)
            else:
                files = _parse_istanbul(raw)
        except Exception:
            continue

        if files:
            return ProjectCoverage(fmt=fmt, source=rel, generated_at=mtime, files=files)
    return None


def _finalize(
    hits: dict[str, dict[int, int]], partials: dict[str, set[int]]
) -> dict[str, FileCoverage]:
    out: dict[str, FileCoverage] = {}
    for path, line_hits in hits.items():
        key = _norm(path)
        fc = out.get(key) or FileCoverage(path=key)
        part = partials.get(path, set())
        for line, count in sorted(line_hits.items()):
            if line in part and count > 0:
                fc.partial.append(line)
            elif count > 0:
                fc.covered.append(line)
            else:
                fc.uncovered.append(line)
        out[key] = fc
    return out


def _parse_cobertura(raw: str) -> dict[str, FileCoverage]:
    root = ET.fromstring(raw)
    sources = [s.text.strip() for s in root.findall("./sources/source") if s.text]
    hits: dict[str, dict[int, int]] = {}
    partials: dict[str, set[int]] = {}

    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        # Cobertura às vezes grava o filename relativo a `<source>` — não
        # tentamos recolar (o casamento por sufixo em `.file()` resolve), só
        # normalizamos.
        line_hits = hits.setdefault(filename, {})
        part = partials.setdefault(filename, set())
        for ln in cls.iter("line"):
            try:
                number = int(ln.get("number", ""))
            except ValueError:
                continue
            count = _to_int(ln.get("hits", "0"))
            line_hits[number] = max(line_hits.get(number, 0), count)
            if ln.get("branch") == "true":
                cc = ln.get("condition-coverage", "")
                m = re.search(r"\((\d+)/(\d+)\)", cc)
                if m and 0 < int(m.group(1)) < int(m.group(2)):
                    part.add(number)
    _ = sources  # mantido para clareza; casamento fica com `.file()`
    return _finalize(hits, partials)


def _parse_lcov(raw: str) -> dict[str, FileCoverage]:
    hits: dict[str, dict[int, int]] = {}
    partials: dict[str, set[int]] = {}
    branch_taken: dict[str, dict[int, list[bool]]] = {}

    current: str | None = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("SF:"):
            current = line[3:].strip()
            hits.setdefault(current, {})
            branch_taken.setdefault(current, {})
        elif line == "end_of_record":
            current = None
        elif current is None:
            continue
        elif line.startswith("DA:"):
            body = line[3:].split(",")
            if len(body) >= 2:
                try:
                    number = int(body[0])
                except ValueError:
                    continue
                hits[current][number] = max(hits[current].get(number, 0), _to_int(body[1]))
        elif line.startswith("BRDA:"):
            body = line[5:].split(",")
            if len(body) >= 4:
                try:
                    number = int(body[0])
                except ValueError:
                    continue
                taken = body[3] != "-" and _to_int(body[3]) > 0
                branch_taken[current].setdefault(number, []).append(taken)

    for path, per_line in branch_taken.items():
        part = partials.setdefault(path, set())
        for number, takens in per_line.items():
            if any(takens) and not all(takens):
                part.add(number)
    return _finalize(hits, partials)


def _parse_istanbul(raw: str) -> dict[str, FileCoverage]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    hits: dict[str, dict[int, int]] = {}
    partials: dict[str, set[int]] = {}

    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not path:
            continue
        line_hits = hits.setdefault(path, {})
        stmt_map = entry.get("statementMap", {}) or {}
        counts = entry.get("s", {}) or {}
        for sid, loc in stmt_map.items():
            try:
                start = int(loc["start"]["line"])
                end = int(loc.get("end", loc["start"]).get("line", loc["start"]["line"]))
            except (KeyError, TypeError, ValueError):
                continue
            count = _to_int(counts.get(sid, 0))
            for number in range(start, max(start, end) + 1):
                line_hits[number] = max(line_hits.get(number, 0), count)

        # Branches parcialmente tomadas → linha parcial.
        branch_map = entry.get("branchMap", {}) or {}
        branch_counts = entry.get("b", {}) or {}
        part = partials.setdefault(path, set())
        for bid, loc in branch_map.items():
            arms = branch_counts.get(bid, []) or []
            if isinstance(arms, list) and len(arms) > 1 and any(arms) and not all(arms):
                try:
                    number = int(loc.get("loc", loc).get("start", {}).get("line"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if number:
                    part.add(number)
    return _finalize(hits, partials)


def _to_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
