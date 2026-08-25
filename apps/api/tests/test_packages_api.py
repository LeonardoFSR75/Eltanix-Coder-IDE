"""Testes da API de Gestão de Pacotes e Sincronização de requirements.txt."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from eltanix.api.routes.packages import (
    parse_requirements_txt,
    sync_requirements_file,
)
from eltanix.main import app

client = TestClient(app)


def test_parse_requirements_txt(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pytest==8.0.0\npandas>=2.0.0\n# comentario\nrequests\n", encoding="utf-8")

    result = parse_requirements_txt(tmp_path)
    assert "pytest" in result
    assert "pandas" in result
    assert "requests" in result
    assert result["pytest"] == "pytest==8.0.0"


def test_parse_requirements_txt_normalizes_underscore_names(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("python_dotenv==1.0.1\nrequests==2.31.0\n", encoding="utf-8")

    result = parse_requirements_txt(tmp_path)
    assert "python-dotenv" in result
    assert result["python-dotenv"] == "python_dotenv==1.0.1"
    assert "requests" in result


def test_sync_requirements_file_add_and_update(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pytest==8.0.0\n", encoding="utf-8")

    # Adiciona novo pacote
    sync_requirements_file(tmp_path, "requests", "2.31.0", remove=False)
    content = req_file.read_text(encoding="utf-8")
    assert "requests==2.31.0" in content
    assert "pytest==8.0.0" in content

    # Atualiza versão existente
    sync_requirements_file(tmp_path, "pytest", "8.3.0", remove=False)
    content_updated = req_file.read_text(encoding="utf-8")
    assert "pytest==8.3.0" in content_updated


def test_sync_requirements_file_remove(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pytest==8.0.0\nrequests==2.31.0\n", encoding="utf-8")

    sync_requirements_file(tmp_path, "requests", remove=True)
    content = req_file.read_text(encoding="utf-8")
    assert "requests" not in content
    assert "pytest==8.0.0" in content


def test_sync_requirements_file_normalizes_case_and_underscores(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pytest==8.0.0\n", encoding="utf-8")

    sync_requirements_file(tmp_path, "Flask", "3.1.0", remove=False)
    content = req_file.read_text(encoding="utf-8")
    assert "flask==3.1.0" in content
    assert "Flask==3.1.0" not in content


def test_export_requirements_from_venv_writes_freeze(tmp_path: Path, monkeypatch):
    from eltanix.api.routes import packages

    venv = tmp_path / ".venv"
    if packages.sys.platform == "win32":
        python_path = venv / "Scripts" / "python.exe"
    else:
        python_path = venv / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("python", encoding="utf-8")

    class FakeCompleted:
        returncode = 0
        stdout = "requests==2.31.0\npytest==8.3.0\n"
        stderr = ""

    monkeypatch.setattr(packages.subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    content = packages.export_requirements_from_venv(tmp_path)

    assert "requests==2.31.0" in content
    assert "pytest==8.3.0" in content
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == (
        "requests==2.31.0\npytest==8.3.0\n"
    )
