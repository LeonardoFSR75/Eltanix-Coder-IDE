"""Testes para `novaai_studio.packages.commands` — a camada de comando/manifesto
compartilhada entre `api/routes/packages.py` (REST) e `agent/tools/packages.py`
(ferramenta do agente). Cobre as duas coisas que valem a pena testar
isoladamente: montagem de argv por ecossistema (sem depender do binário estar
no PATH) e parsing de manifesto estático."""

from __future__ import annotations

from pathlib import Path

from novaai_studio.packages.commands import (
    MissingBinaryError,
    build_ecosystem_command,
    list_python_packages,
    parse_installed_packages,
    run_dependency_audit,
)


def test_build_ecosystem_command_python_uses_pip(tmp_path: Path):
    py_exe = tmp_path / "python.exe"
    cmd = build_ecosystem_command(
        "python", "install", project_path=tmp_path, package="requests", py_exe=py_exe
    )
    assert cmd == [str(py_exe), "-m", "pip", "install", "requests"]


def test_build_ecosystem_command_python_sync_reads_requirements(tmp_path: Path):
    py_exe = tmp_path / "python.exe"
    cmd = build_ecosystem_command(
        "python", "sync", project_path=tmp_path, package=None, py_exe=py_exe
    )
    assert cmd == [
        str(py_exe),
        "-m",
        "pip",
        "install",
        "-r",
        str(tmp_path / "requirements.txt"),
    ]


def test_build_ecosystem_command_python_uninstall_is_non_interactive(tmp_path: Path):
    py_exe = tmp_path / "python.exe"
    cmd = build_ecosystem_command(
        "python", "uninstall", project_path=tmp_path, package="requests", py_exe=py_exe
    )
    assert "-y" in cmd


def test_build_ecosystem_command_raises_when_binary_missing(tmp_path: Path, monkeypatch):
    from novaai_studio.packages import commands

    monkeypatch.setattr(commands.shutil, "which", lambda _name: None)
    for eco in ("nodejs", "go", "rust", "php"):
        try:
            commands.build_ecosystem_command(
                eco, "install", project_path=tmp_path, package="x", py_exe=tmp_path / "py"
            )
            raise AssertionError(f"esperava MissingBinaryError para {eco}")
        except MissingBinaryError:
            pass


def test_build_ecosystem_command_nodejs(tmp_path: Path, monkeypatch):
    from novaai_studio.packages import commands

    monkeypatch.setattr(commands.shutil, "which", lambda _name: "/usr/bin/npm")
    cmd = build_ecosystem_command(
        "nodejs", "install", project_path=tmp_path, package="lodash", py_exe=tmp_path / "py"
    )
    assert cmd == ["/usr/bin/npm", "install", "lodash"]


def test_parse_installed_packages_nodejs(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"react": "18.0.0"}, "devDependencies": {"vite": "5.0.0"}}',
        encoding="utf-8",
    )
    result = parse_installed_packages(tmp_path, "nodejs")
    names = {p["name"] for p in result}
    assert names == {"react", "vite"}


def test_parse_installed_packages_go(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        "module example.com/app\n\ngo 1.22\n\nrequire (\n\tgithub.com/gorilla/mux v1.8.1\n)\n",
        encoding="utf-8",
    )
    result = parse_installed_packages(tmp_path, "go")
    assert {"name": "github.com/gorilla/mux", "version": "v1.8.1"} in result


def test_parse_installed_packages_rust(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0"\n',
        encoding="utf-8",
    )
    result = parse_installed_packages(tmp_path, "rust")
    assert {"name": "serde", "version": "1.0"} in result


def test_parse_installed_packages_php(tmp_path: Path):
    (tmp_path / "composer.json").write_text(
        '{"require": {"php": ">=8.1", "monolog/monolog": "^3.0"}}', encoding="utf-8"
    )
    result = parse_installed_packages(tmp_path, "php")
    assert result == [{"name": "monolog/monolog", "version": "^3.0"}]


def test_parse_installed_packages_missing_manifest_returns_empty(tmp_path: Path):
    assert parse_installed_packages(tmp_path, "nodejs") == []
    assert parse_installed_packages(tmp_path, "go") == []
    assert parse_installed_packages(tmp_path, "rust") == []
    assert parse_installed_packages(tmp_path, "php") == []


async def test_list_python_packages_without_venv_returns_empty(tmp_path: Path):
    result = await list_python_packages(tmp_path / ".venv" / "python.exe", tmp_path)
    assert result == []


async def test_run_dependency_audit_unsupported_ecosystem(tmp_path: Path):
    result = await run_dependency_audit("go", tmp_path, tmp_path / "py")
    assert result["supported"] is False
    assert result["vulnerabilities"] == []


async def test_run_dependency_audit_python_without_pip_audit(tmp_path: Path, monkeypatch):
    from novaai_studio.packages import commands

    monkeypatch.setattr(commands.shutil, "which", lambda _name: None)
    result = await run_dependency_audit("python", tmp_path, tmp_path / "py")
    assert result["supported"] is True
    assert result["tool_available"] is False
    assert result["vulnerabilities"] == []


async def test_run_dependency_audit_nodejs_without_npm(tmp_path: Path, monkeypatch):
    from novaai_studio.packages import commands

    monkeypatch.setattr(commands.shutil, "which", lambda _name: None)
    result = await run_dependency_audit("nodejs", tmp_path, tmp_path / "py")
    assert result["supported"] is True
    assert result["tool_available"] is False
    assert result["vulnerabilities"] == []
