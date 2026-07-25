"""Varredura do workspace: o que entra no índice e o que fica de fora.

Respeitar o `.gitignore` não é cortesia — é o que impede o índice de engolir
`node_modules`, `.venv` e artefatos de build, que somam mais bytes que o código
e não respondem pergunta nenhuma.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pathspec

from sicoobito.context.languages import detect_language
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Arquivo maior que isto quase sempre é dado ou artefato, não código-fonte.
MAX_FILE_BYTES = 512 * 1024

# Ignorados mesmo sem .gitignore: diretórios que nenhum repositório quer indexar.
ALWAYS_IGNORED = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    ".sicoobito",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".jar", ".war",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".pyc", ".pyd",
    ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".avi",
    ".sqlite", ".sqlite3", ".db", ".lock",
}


@dataclass(slots=True)
class ScannedFile:
    path: str
    absolute: Path
    content_hash: str
    size_bytes: int
    mtime: float
    language: str | None


def _load_ignore_spec(root: Path) -> pathspec.PathSpec:
    patterns: list[str] = []
    for name in (".gitignore", ".sicoobitoignore"):
        candidate = root / name
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8", errors="replace")
                patterns.extend(content.splitlines())
            except OSError as exc:
                log.warning("scanner.ignore.unreadable", file=str(candidate), error=str(exc))
    # "gitignore" e não "gitwildmatch": este último está deprecado no pathspec
    # e não implementa a semântica completa de precedência do Git.
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _looks_binary(data: bytes) -> bool:
    # Byte nulo nos primeiros KB é o sinal mais confiável e mais barato.
    return b"\x00" in data[:4096]


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text(path: Path) -> str | None:
    """Lê o arquivo como texto, devolvendo None se for binário ou ilegível."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        log.debug("scanner.read.failed", path=str(path), error=str(exc))
        return None
    if _looks_binary(data):
        return None
    return data.decode("utf-8", errors="replace")


def scan(root: Path) -> Iterator[ScannedFile]:
    root = root.resolve()
    spec = _load_ignore_spec(root)

    for absolute in root.rglob("*"):
        if not absolute.is_file():
            continue

        try:
            relative = absolute.relative_to(root)
        except ValueError:  # pragma: no cover - rglob não deveria sair da raiz
            continue

        parts = set(relative.parts)
        if parts & ALWAYS_IGNORED:
            continue
        if absolute.suffix.lower() in BINARY_EXTENSIONS:
            continue

        # `as_posix` porque padrões de .gitignore usam barra normal, inclusive
        # no Windows.
        relative_posix = relative.as_posix()
        if spec.match_file(relative_posix):
            continue

        try:
            stat = absolute.stat()
        except OSError:
            continue
        if stat.st_size > MAX_FILE_BYTES or stat.st_size == 0:
            continue

        try:
            data = absolute.read_bytes()
        except OSError:
            continue
        if _looks_binary(data):
            continue

        yield ScannedFile(
            path=relative_posix,
            absolute=absolute,
            content_hash=hash_bytes(data),
            size_bytes=stat.st_size,
            mtime=stat.st_mtime,
            language=detect_language(absolute.name),
        )
