"""Descoberta e resolução de projetos.

O IDE abre projetos diferentes ao longo do dia, então `PROJECTS_ROOT` aponta
para a pasta que os contém e cada subdiretório é um projeto. Índice, sessões de
agente e operações de git passam a ser escopados por projeto.

`PROJECTS_ROOT` é a fronteira: nenhum caminho fora dela é alcançável, e o nome
do projeto é validado como um único segmento — `..` e barras não passam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Um segmento de caminho, sem separador e sem `..`.
_NOME_VALIDO = re.compile(r"^[A-Za-z0-9._-][A-Za-z0-9 ._-]{0,127}$")

_IGNORADOS = {".git", "node_modules", ".venv", "__pycache__", ".sicoobito", "$RECYCLE.BIN"}


class ProjectError(ValueError):
    pass


@dataclass(slots=True)
class Project:
    name: str
    path: Path
    is_git: bool
    branch: str | None = None


def validate_name(name: str) -> str:
    """Aceita apenas um segmento simples. `..`, `/` e `\\` são recusados."""
    limpo = (name or "").strip()
    if not limpo or limpo in {".", ".."} or not _NOME_VALIDO.match(limpo):
        raise ProjectError(
            f"Nome de projeto inválido: {name!r}. Use apenas o nome da pasta, "
            "sem barras nem '..'."
        )
    return limpo


def resolve(projects_root: Path, name: str) -> Path:
    """Caminho absoluto do projeto, garantidamente dentro da raiz."""
    raiz = projects_root.resolve()
    destino = (raiz / validate_name(name)).resolve()
    # Mesmo com o nome validado, a checagem final cobre symlink apontando fora.
    if destino != raiz and raiz not in destino.parents:
        raise ProjectError(f"Projeto fora de PROJECTS_ROOT: {name}")
    if not destino.is_dir():
        raise ProjectError(f"Projeto não encontrado: {name}")
    return destino


def _branch_of(path: Path) -> str | None:
    """Lê o branch direto do `.git/HEAD`.

    Evita abrir o repositório com o GitPython só para listar: numa pasta com
    dezenas de projetos, isso custaria centenas de milissegundos.
    """
    head = path / ".git" / "HEAD"
    try:
        conteudo = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if conteudo.startswith("ref:"):
        return conteudo.split("/")[-1]
    return conteudo[:8] or None


def list_projects(projects_root: Path) -> list[Project]:
    raiz = projects_root.resolve()
    if not raiz.is_dir():
        log.warning("projects.root.missing", path=str(raiz))
        return []

    projetos: list[Project] = []
    for filho in sorted(raiz.iterdir(), key=lambda p: p.name.lower()):
        if not filho.is_dir() or filho.name in _IGNORADOS or filho.name.startswith("."):
            continue
        eh_git = (filho / ".git").exists()
        projetos.append(
            Project(
                name=filho.name,
                path=filho,
                is_git=eh_git,
                branch=_branch_of(filho) if eh_git else None,
            )
        )
    return projetos
