"""Varredura do workspace: o que entra no índice e o que fica de fora.

Respeitar o `.gitignore` não é cortesia — é o que impede o índice de engolir
`node_modules`, `.venv` e artefatos de build, que somam mais bytes que o código
e não respondem pergunta nenhuma.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pathspec

from novaai_studio.context.languages import detect_language
from novaai_studio.logging_setup import get_logger

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
    ".novaai_studio",
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".svg",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".rar",
    ".jar",
    ".war",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".o",
    ".a",
    ".pyc",
    ".pyd",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".lock",
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
    for name in (".gitignore", ".novaai_studioignore"):
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
    """Lê o arquivo como texto, devolvendo None se for binário ou ilegível.

    Decodifica UTF-8 estrito — não `errors="replace"`: um arquivo salvo em
    outro encoding (Latin-1, CP-1252, UTF-16...) decodificado com replace vira
    `U+FFFD` silenciosamente, e como `WorkspaceFS.write()` sempre grava UTF-8,
    um simples abrir-e-salvar sem editar nada corromperia os bytes originais
    para sempre, sem aviso. Tratar como ilegível (mesmo caminho de "binário")
    é mais seguro que perder dado silenciosamente.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        log.debug("scanner.read.failed", path=str(path), error=str(exc))
        return None
    if _looks_binary(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        log.debug("scanner.read.not_utf8", path=str(path))
        return None


def iter_paths(root: Path) -> Iterator[tuple[str, Path, int]]:
    """Caminhos do projeto, **sem ler o conteúdo** dos arquivos.

    Existe separado de `scan` porque listar não é indexar. O `scan` lê os bytes
    de cada arquivo para calcular hash e detectar binário — necessário para
    indexar, desperdício para preencher um quick open. Sobre bind mount de
    Windows para Linux a diferença é de segundos para um minuto num projeto de
    mil arquivos.

    Devolve `(caminho relativo, caminho absoluto, tamanho)`.
    """
    root = root.resolve()
    spec = _load_ignore_spec(root)

    for dirpath, dirnames, filenames in os.walk(root):
        atual = Path(dirpath)

        mantidos = []
        for nome in dirnames:
            if nome in ALWAYS_IGNORED:
                continue
            relativo = (atual / nome).relative_to(root).as_posix()
            if spec.match_file(f"{relativo}/") or spec.match_file(relativo):
                continue
            mantidos.append(nome)
        dirnames[:] = mantidos

        for nome in filenames:
            absolute = atual / nome
            if absolute.suffix.lower() in BINARY_EXTENSIONS:
                continue
            relative_posix = absolute.relative_to(root).as_posix()
            if spec.match_file(relative_posix):
                continue
            try:
                tamanho = absolute.stat().st_size
            except OSError:
                continue
            if tamanho > MAX_FILE_BYTES or tamanho == 0:
                continue
            yield relative_posix, absolute, tamanho


def scan(root: Path) -> Iterator[ScannedFile]:
    """Percorre o projeto, **podando** diretórios ignorados antes de descer.

    A poda é o ponto crítico. `Path.rglob("*")` visita tudo e só então filtra:
    num projeto com `node_modules` e `.venv`, isso significa percorrer centenas
    de milhares de entradas para descartar quase todas. Sobre um bind mount de
    Windows para container Linux, onde cada chamada ao filesystem cruza uma
    fronteira, a varredura passa de segundos para dezenas de minutos.

    `os.walk` permite alterar a lista de subdiretórios no lugar, e é isso que
    impede a descida.
    """
    root = root.resolve()
    spec = _load_ignore_spec(root)

    for dirpath, dirnames, filenames in os.walk(root):
        atual = Path(dirpath)

        # Poda: o que sai daqui não é sequer visitado.
        mantidos = []
        for nome in dirnames:
            if nome in ALWAYS_IGNORED:
                continue
            relativo = (atual / nome).relative_to(root).as_posix()
            # O padrão com barra final é o que casa regra de diretório no
            # gitignore ("build/" não casa com "build" sozinho).
            if spec.match_file(f"{relativo}/") or spec.match_file(relativo):
                continue
            mantidos.append(nome)
        dirnames[:] = mantidos

        for nome in filenames:
            absolute = atual / nome
            if absolute.suffix.lower() in BINARY_EXTENSIONS:
                continue

            # `as_posix` porque padrões de .gitignore usam barra normal,
            # inclusive no Windows.
            relative_posix = absolute.relative_to(root).as_posix()
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
