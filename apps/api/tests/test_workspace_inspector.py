"""Testes unitários para PathGuard, ProjectInspector e endpoint de abertura de caminhos arbitrários."""

from pathlib import Path
import pytest
from sicoobito.workspace.path_guard import PathGuard, PathEscapeError
from sicoobito.workspace.inspector import ProjectInspector


def test_path_guard_allow_and_validate(tmp_path: Path):
    guard = PathGuard()
    
    sub_dir = tmp_path / "meu_projeto"
    sub_dir.mkdir()
    
    # Inicialmente não autorizado
    assert not guard.is_allowed(sub_dir)
    with pytest.raises(PathEscapeError):
        guard.validate(sub_dir)

    # Autoriza o caminho
    guard.allow(sub_dir)
    assert guard.is_allowed(sub_dir)
    assert guard.validate(sub_dir) == sub_dir.resolve()

    # Valida subarquivo sob o caminho autorizado
    sub_file = sub_dir / "src" / "index.js"
    assert guard.is_allowed(sub_file)


def test_project_inspector_signatures(tmp_path: Path):
    inspector = ProjectInspector()

    # Simula projeto Node/Next.js/Docker
    proj = tmp_path / "meu_next_app"
    proj.mkdir()
    (proj / "package.json").write_text('{"dependencies": {"next": "15.0.0", "react": "19.0.0"}}', encoding="utf-8")
    (proj / "docker-compose.yml").write_text("version: '3.8'", encoding="utf-8")
    (proj / ".git").mkdir()

    sig = inspector.inspect(proj)

    assert sig.name == "meu_next_app"
    assert sig.primary_language in ("TypeScript/JavaScript", "TypeScript")
    assert "Next.js" in sig.frameworks
    assert "React" in sig.frameworks
    assert sig.has_docker is True
    assert sig.has_git is True
    assert "Next.js" in sig.executive_summary
