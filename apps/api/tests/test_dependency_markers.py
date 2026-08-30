"""Mapeamento CVE → linha do manifesto (Onda 1.5 — gutter intelligence)."""

from __future__ import annotations

from eltanix.workspace.dependency_markers import (
    is_manifest,
    markers_from_audit,
)

PIP_AUDIT = {
    "supported": True,
    "ecosystem": "python",
    "tool": "pip-audit",
    "tool_available": True,
    "vulnerabilities": [
        {
            "package": "Jinja2",
            "installed_version": "3.1.2",
            "id": "GHSA-h5c8-rqwp-cp95",
            "fix_versions": ["3.1.3"],
            "description": "Jinja2 XSS via xmlattr filter",
        },
        {
            "package": "jinja2",
            "installed_version": "3.1.2",
            "id": "GHSA-h75v-3vvj-5mfj",
            "fix_versions": ["3.1.4"],
            "description": "Another jinja issue",
        },
        {
            "package": "requests",
            "installed_version": "2.28.0",
            "id": "CVE-2023-32681",
            "fix_versions": ["2.31.0"],
            "description": "Proxy-Authorization leak",
        },
    ],
}

NPM_AUDIT = {
    "supported": True,
    "ecosystem": "nodejs",
    "tool": "npm audit",
    "tool_available": True,
    "vulnerabilities": [
        {"package": "lodash", "severity": "high", "range": "<4.17.21", "fix_available": True},
        {"package": "minimist", "severity": "critical", "range": "<1.2.6", "fix_available": False},
    ],
}


def test_is_manifest() -> None:
    assert is_manifest("requirements.txt")
    assert is_manifest("apps/api/requirements.txt")
    assert is_manifest("package.json")
    assert not is_manifest("src/main.py")
    assert not is_manifest("package-lock.json")


def test_requirements_markers_merge_by_package_and_anchor_line() -> None:
    text = "# deps\nflask==2.0\njinja2==3.1.2\nrequests>=2.28\n"
    markers = markers_from_audit("requirements.txt", text, PIP_AUDIT)
    assert [m.line for m in markers] == [3, 4]
    jinja = markers[0]
    assert jinja.package == "jinja2"
    assert set(jinja.ids) == {"GHSA-h5c8-rqwp-cp95", "GHSA-h75v-3vvj-5mfj"}
    assert "3.1.3" in (jinja.fix or "")
    assert markers[1].package == "requests"


def test_requirements_skips_packages_not_in_file() -> None:
    text = "flask==2.0\n"
    assert markers_from_audit("requirements.txt", text, PIP_AUDIT) == []


def test_package_json_markers_use_declared_dependency_lines() -> None:
    text = (
        "{\n"
        '  "name": "app",\n'
        '  "dependencies": {\n'
        '    "lodash": "^4.17.20",\n'
        '    "express": "^4.18.0"\n'
        "  },\n"
        '  "devDependencies": {\n'
        '    "minimist": "1.2.5"\n'
        "  }\n"
        "}\n"
    )
    markers = markers_from_audit("package.json", text, NPM_AUDIT)
    by_pkg = {m.package: m for m in markers}
    assert by_pkg["lodash"].line == 4
    assert by_pkg["lodash"].severity == "high"
    assert by_pkg["minimist"].line == 8
    assert by_pkg["minimist"].severity == "critical"


def test_empty_audit_yields_no_markers() -> None:
    assert markers_from_audit("requirements.txt", "jinja2==3.1.2\n", {"vulnerabilities": []}) == []


def test_unknown_manifest_name_yields_nothing() -> None:
    assert markers_from_audit("Pipfile", "jinja2 = '*'\n", PIP_AUDIT) == []
