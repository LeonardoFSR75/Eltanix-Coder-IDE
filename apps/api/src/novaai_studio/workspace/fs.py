"""Acesso a arquivos do workspace, com a raiz como fronteira rígida.

Toda leitura e escrita do agente passa por aqui. É o único ponto onde um
caminho vindo do modelo vira caminho de disco, e portanto o único lugar onde
`../`, caminho absoluto e symlink apontando para fora precisam ser barrados.

Um modelo não precisa ser malicioso para pedir `../../.ssh/id_rsa` — basta
alucinar. E conteúdo de README ou de issue entra no contexto como dado; se algo
ali sugerir um caminho, ele chega até aqui.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from novaai_studio.context.scanner import (
    ALWAYS_IGNORED,
    BINARY_EXTENSIONS,
    MAX_FILE_BYTES,
    read_text,
)
from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)


class PathEscapeError(ValueError):
    """Caminho pedido cai fora da raiz do workspace."""

    def __init__(self, requested: str, root: Path) -> None:
        super().__init__(
            f"Caminho fora do workspace: {requested!r} não está sob {root}. "
            "Use caminhos relativos à raiz do projeto."
        )
        self.requested = requested
        self.root = root


class FileTooLargeError(ValueError):
    pass


@dataclass(slots=True)
class FileEntry:
    path: str
    is_dir: bool
    size_bytes: int


class WorkspaceFS:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve(self, relative: str) -> Path:
        """Converte caminho relativo em absoluto, recusando qualquer fuga.

        `Path.resolve()` já normaliza `..` e segue symlink; a comparação depois
        disso é o que garante que o resultado final continua dentro da raiz —
        checar a string antes de resolver seria contornável por link simbólico.
        """
        if not relative or not relative.strip():
            raise PathEscapeError(relative, self.root)

        candidate = Path(relative.strip().replace("\\", "/"))
        if candidate.is_absolute() or candidate.drive:
            # Caminho absoluto até pode apontar para dentro, mas aceitar isso
            # abre espaço para erro silencioso; exigimos relativo.
            raise PathEscapeError(relative, self.root)

        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise PathEscapeError(relative, self.root)
        return resolved

    def relative(self, absolute: Path) -> str:
        return absolute.resolve().relative_to(self.root).as_posix()

    def exists(self, relative: str) -> bool:
        try:
            return self.resolve(relative).exists()
        except PathEscapeError:
            return False

    def read(self, relative: str, *, max_bytes: int = MAX_FILE_BYTES) -> str:
        target = self.resolve(relative)
        if not target.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {relative}")

        size = target.stat().st_size
        if size > max_bytes:
            raise FileTooLargeError(
                f"{relative} tem {size} bytes (limite {max_bytes}). Leia um trecho com read_lines."
            )

        content = read_text(target)
        if content is None:
            raise ValueError(f"{relative} parece binário e não pode ser lido como texto.")
        return content

    def read_lines(self, relative: str, start: int = 1, end: int | None = None) -> str:
        """Lê um intervalo de linhas, 1-based e inclusivo nas duas pontas."""
        content = self.read(relative)
        lines = content.splitlines()
        start = max(1, start)
        end = len(lines) if end is None else min(end, len(lines))
        selected = lines[start - 1 : end]
        # A numeração vai junto: sem ela o modelo erra ao pedir uma edição por
        # linha logo depois de ler.
        width = len(str(end))
        return "\n".join(f"{start + i:>{width}}  {line}" for i, line in enumerate(selected))

    def write(self, relative: str, content: str) -> int:
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        # newline="" preserva exatamente o que o chamador montou, sem o Python
        # traduzir \n para \r\n no Windows e sujar o diff inteiro.
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        log.info("workspace.write", path=relative, bytes=len(content))
        return len(content)

    def create(self, relative: str, *, content: str = "", is_dir: bool = False) -> str:
        """Cria arquivo ou pasta. Recusa sobrescrever o que já existe."""
        target = self.resolve(relative)
        if target.exists():
            raise FileExistsError(f"{relative} já existe.")

        if is_dir:
            target.mkdir(parents=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        log.info("workspace.create", path=relative, is_dir=is_dir)
        return self.relative(target)

    def move(self, origem: str, destino: str) -> str:
        """Move ou renomeia. As duas pontas passam pela mesma fronteira."""
        de = self.resolve(origem)
        para = self.resolve(destino)

        if not de.exists():
            raise FileNotFoundError(f"{origem} não existe.")
        if para.exists():
            raise FileExistsError(f"{destino} já existe.")
        # Mover uma pasta para dentro de si mesma apagaria a árvore inteira.
        if de.is_dir() and de in para.parents:
            raise ValueError(f"Não é possível mover {origem} para dentro dele mesmo.")

        para.parent.mkdir(parents=True, exist_ok=True)
        de.rename(para)
        log.info("workspace.move", origem=origem, destino=destino)
        return self.relative(para)

    def delete(self, relative: str, *, recursive: bool = False) -> None:
        target = self.resolve(relative)
        if target.is_dir():
            if not recursive:
                raise IsADirectoryError(
                    f"{relative} é um diretório. Confirme a remoção recursiva para excluí-lo."
                )
            # A raiz do workspace nunca é apagável, mesmo com recursive.
            if target == self.root:
                raise ValueError("A raiz do projeto não pode ser removida.")
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        log.info("workspace.delete", path=relative, recursive=recursive)

    def list_dir(self, relative: str = ".") -> list[FileEntry]:
        target = self.resolve(relative) if relative not in {"", "."} else self.root
        if not target.is_dir():
            raise NotADirectoryError(f"{relative} não é um diretório.")

        entries: list[FileEntry] = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            # Mesma lista do scanner: divergir faria a árvore mostrar pastas
            # que a busca e a indexação ignoram.
            if child.name in ALWAYS_IGNORED:
                continue
            try:
                size = child.stat().st_size if child.is_file() else 0
            except OSError:
                continue
            entries.append(
                FileEntry(path=self.relative(child), is_dir=child.is_dir(), size_bytes=size)
            )
        return entries

    def is_text_file(self, relative: str) -> bool:
        try:
            target = self.resolve(relative)
        except PathEscapeError:
            return False
        return target.is_file() and target.suffix.lower() not in BINARY_EXTENSIONS
