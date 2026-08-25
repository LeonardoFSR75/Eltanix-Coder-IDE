from __future__ import annotations

from pathlib import Path

from novaai_studio.context.scanner import MAX_FILE_BYTES, read_text, scan


def _build_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('oi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Projeto\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("segredos/\n*.log\n", encoding="utf-8")

    (tmp_path / "segredos").mkdir()
    (tmp_path / "segredos" / "chave.py").write_text("KEY = 1\n", encoding="utf-8")
    (tmp_path / "app.log").write_text("linha\n", encoding="utf-8")

    (tmp_path / "node_modules" / "pacote").mkdir(parents=True)
    (tmp_path / "node_modules" / "pacote" / "index.js").write_text("x", encoding="utf-8")

    (tmp_path / "imagem.png").write_bytes(b"\x89PNG\x00\x00dados")
    return tmp_path


def test_scan_respects_gitignore(tmp_path):
    paths = {f.path for f in scan(_build_repo(tmp_path))}

    assert "src/app.py" in paths
    assert "README.md" in paths
    # Ignorados pelo .gitignore.
    assert "segredos/chave.py" not in paths
    assert "app.log" not in paths


def test_scan_skips_dependency_and_build_dirs(tmp_path):
    paths = {f.path for f in scan(_build_repo(tmp_path))}
    assert not any(p.startswith("node_modules") for p in paths)


def test_scan_skips_binary_files(tmp_path):
    paths = {f.path for f in scan(_build_repo(tmp_path))}
    assert "imagem.png" not in paths


def test_scan_uses_posix_paths(tmp_path):
    # Padrões de .gitignore usam barra normal; no Windows, path do SO quebraria
    # a correspondência.
    paths = {f.path for f in scan(_build_repo(tmp_path))}
    assert all("\\" not in p for p in paths)


def test_scan_detects_language(tmp_path):
    files = {f.path: f for f in scan(_build_repo(tmp_path))}
    assert files["src/app.py"].language == "python"
    assert files["README.md"].language == "markdown"


def test_hash_changes_with_content(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    antes = next(f for f in scan(tmp_path) if f.path == "a.py").content_hash

    target.write_text("x = 2\n", encoding="utf-8")
    depois = next(f for f in scan(tmp_path) if f.path == "a.py").content_hash

    assert antes != depois


def test_oversized_file_is_skipped(tmp_path):
    (tmp_path / "grande.py").write_text("#" * (MAX_FILE_BYTES + 10), encoding="utf-8")
    assert "grande.py" not in {f.path for f in scan(tmp_path)}


def test_empty_file_is_skipped(tmp_path):
    (tmp_path / "vazio.py").write_text("", encoding="utf-8")
    assert "vazio.py" not in {f.path for f in scan(tmp_path)}


def test_read_text_returns_none_for_binary(tmp_path):
    binario = tmp_path / "dados.bin"
    binario.write_bytes(b"abc\x00def")
    assert read_text(binario) is None


def test_read_text_returns_none_for_invalid_utf8(tmp_path):
    """Decodificar com errors="replace" corromperia o arquivo em silêncio no
    próximo save (WorkspaceFS.write sempre grava UTF-8) — tratar como
    ilegível, igual a um binário, evita perda de dado sem aviso."""
    arquivo = tmp_path / "latin.py"
    arquivo.write_bytes("comentário".encode("latin-1"))
    assert read_text(arquivo) is None
