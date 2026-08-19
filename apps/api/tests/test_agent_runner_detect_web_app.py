"""`_detect_web_app` (`agent/runner.py`): heurística de auto-aquecimento do
sandbox — sem cobertura antes desta mudança. Passou a rodar via
`asyncio.to_thread` em `create_session` (item 11 do plano de robustez do
navegador interno, I/O bloqueante de `Path.exists()`/`.iterdir()`/
`.read_text()` tirado do event loop); estes testes travam o comportamento da
função pura em si.
"""

from __future__ import annotations

from pathlib import Path

from sicoobito.agent.runner import _detect_web_app


def test_detect_web_app_false_for_empty_or_missing_directory(tmp_path: Path):
    assert _detect_web_app(tmp_path) is False
    assert _detect_web_app(tmp_path / "nao-existe") is False


def test_detect_web_app_true_for_flask_requirements(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('oi')")
    (tmp_path / "requirements.txt").write_text("flask==3.0\n")

    assert _detect_web_app(tmp_path) is True


def test_detect_web_app_true_for_react_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')

    assert _detect_web_app(tmp_path) is True


def test_detect_web_app_true_for_static_folder_indicator(tmp_path: Path):
    (tmp_path / "templates").mkdir()

    assert _detect_web_app(tmp_path) is True


def test_detect_web_app_false_for_plain_python_library(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('oi')")
    (tmp_path / "requirements.txt").write_text("numpy==2.0\npandas==2.2\n")

    assert _detect_web_app(tmp_path) is False
