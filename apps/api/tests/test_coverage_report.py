"""Parsers de relatório de cobertura (Onda 1.5 — gutter intelligence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eltanix.workspace.coverage import load_project_coverage

COBERTURA = """<?xml version="1.0" ?>
<coverage line-rate="0.75" version="7.0" timestamp="0">
  <sources><source>/build/ci/checkout</source></sources>
  <packages>
    <package name="pkg" line-rate="0.75">
      <classes>
        <class filename="src/pkg/mod.py" name="mod.py" line-rate="0.75">
          <lines>
            <line number="1" hits="3"/>
            <line number="2" hits="0"/>
            <line number="5" hits="1" branch="true" condition-coverage="50% (1/2)"/>
            <line number="6" hits="2" branch="true" condition-coverage="100% (2/2)"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

LCOV = """TN:
SF:src/app/thing.ts
DA:1,4
DA:2,0
DA:3,1
BRDA:3,0,0,2
BRDA:3,0,1,0
FN:1,thing
end_of_record
SF:src/app/other.ts
DA:10,0
end_of_record
"""

ISTANBUL = """{
  "/abs/repo/src/app/thing.js": {
    "path": "/abs/repo/src/app/thing.js",
    "statementMap": {
      "0": {"start": {"line": 1}, "end": {"line": 1}},
      "1": {"start": {"line": 2}, "end": {"line": 3}},
      "2": {"start": {"line": 7}, "end": {"line": 7}}
    },
    "s": {"0": 5, "1": 0, "2": 2},
    "branchMap": {"0": {"loc": {"start": {"line": 7}}}},
    "b": {"0": [2, 0]}
  }
}
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return tmp_path


def test_no_report_returns_none(tmp_path: Path) -> None:
    assert load_project_coverage(tmp_path) is None


def test_cobertura_splits_covered_uncovered_partial(tmp_path: Path) -> None:
    _write(tmp_path, "coverage.xml", COBERTURA)
    data = load_project_coverage(tmp_path)
    assert data is not None and data.fmt == "cobertura"
    fc = data.file("src/pkg/mod.py")
    assert fc is not None
    assert fc.covered == [1, 6]
    assert fc.uncovered == [2]
    assert fc.partial == [5]
    assert 0.0 < fc.line_rate < 1.0


def test_cobertura_matches_by_path_suffix(tmp_path: Path) -> None:
    _write(tmp_path, "coverage.xml", COBERTURA.replace('filename="src/pkg/mod.py"', 'filename="/build/ci/checkout/src/pkg/mod.py"'))
    data = load_project_coverage(tmp_path)
    assert data is not None
    assert data.file("src/pkg/mod.py") is not None
    assert data.file("pkg/mod.py") is not None
    assert data.file("totally/unrelated.py") is None


def test_lcov_uses_da_and_marks_partial_branch(tmp_path: Path) -> None:
    _write(tmp_path, "lcov.info", LCOV)
    data = load_project_coverage(tmp_path)
    assert data is not None and data.fmt == "lcov"
    fc = data.file("src/app/thing.ts")
    assert fc is not None
    assert fc.covered == [1]
    assert fc.uncovered == [2]
    assert fc.partial == [3]
    other = data.file("src/app/other.ts")
    assert other is not None and other.uncovered == [10]


def test_istanbul_expands_statement_ranges(tmp_path: Path) -> None:
    _write(tmp_path, "coverage/coverage-final.json", ISTANBUL)
    data = load_project_coverage(tmp_path)
    assert data is not None and data.fmt == "istanbul"
    fc = data.file("src/app/thing.js")
    assert fc is not None
    assert fc.covered == [1]
    assert fc.uncovered == [2, 3]
    # statement 2 na linha 7 tem hits, mas a branch é parcial → linha 7 parcial
    assert fc.partial == [7]


def test_malformed_report_is_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "coverage.xml", "<coverage><broken")
    assert load_project_coverage(tmp_path) is None


@pytest.mark.parametrize("name", ["coverage.xml", "lcov.info", "coverage/coverage-final.json"])
def test_empty_file_is_ignored(tmp_path: Path, name: str) -> None:
    _write(tmp_path, name, "")
    assert load_project_coverage(tmp_path) is None
