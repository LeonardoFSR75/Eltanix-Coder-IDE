"""Diff a partir de argumentos PROPOSTOS de ferramenta — antes de qualquer
escrita em disco.

Usado por duas features que precisam "ver" o que uma chamada de `edit_file`/
`write_file` faria, sem executá-la: a política de auto-aprovação (regras de
tamanho de diff) e a segunda opinião automática pré-aprovação. Puramente de
leitura — nunca escreve nada, e qualquer falha (arquivo inexistente, caminho
fora do workspace, trecho ambíguo) degrada para `None`, não para exceção.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eltanix.agent.tools.base import ToolContext
from eltanix.agent.tools.files import unified_diff
from eltanix.workspace.fs import FileTooLargeError, PathEscapeError

# Único lugar que decide quais ferramentas têm conceito de diff — consultado
# também por `agent/graph.py` (diff preview, segunda opinião, snapshot de
# rewind), em vez de cada um manter sua própria lista de nomes que precisa
# ser atualizada em conjunto sempre que uma ferramenta diffável nova aparecer.
REVIEWABLE_TOOL_NAMES = frozenset({"edit_file", "write_file"})


@dataclass(slots=True)
class ProposedDiff:
    path: str
    before: str
    after: str
    diff: str
    changed_lines: int
    existed: bool


def _count_changed_lines(diff: str) -> int:
    # Conta só as linhas de conteúdo (+/-), não os cabeçalhos ---/+++.
    return sum(
        1
        for linha in diff.splitlines()
        if (linha.startswith("+") and not linha.startswith("+++"))
        or (linha.startswith("-") and not linha.startswith("---"))
    )


def compute_proposed_diff(
    ctx: ToolContext, tool_name: str, arguments: dict[str, Any]
) -> ProposedDiff | None:
    """Best-effort: retorna `None` para ferramentas sem conceito de diff (ex.
    `run_command`) ou em qualquer falha de leitura — quem chama trata `None`
    como "sem informação disponível", nunca como erro a propagar."""
    path = arguments.get("path")
    if not path:
        return None

    if tool_name not in REVIEWABLE_TOOL_NAMES:
        return None
    if tool_name == "edit_file":
        return _diff_for_edit_file(ctx, path, arguments)
    return _diff_for_write_file(ctx, path, arguments)


def _diff_for_edit_file(
    ctx: ToolContext, path: str, arguments: dict[str, Any]
) -> ProposedDiff | None:
    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")
    if old_text is None or new_text is None:
        return None

    try:
        atual = ctx.fs.read(path)
    except (PathEscapeError, FileNotFoundError, FileTooLargeError, ValueError):
        return None

    atual_norm = atual.replace("\r\n", "\n")
    old_norm = old_text.replace("\r\n", "\n")
    new_norm = new_text.replace("\r\n", "\n")

    # Mesma regra de `edit_file`: só faz sentido "prever" o diff quando o
    # trecho é inequívoco — 0 ou várias ocorrências são um erro que a própria
    # ferramenta vai recusar na hora de executar, não um diff válido pra
    # avaliar agora.
    if atual_norm.count(old_norm) != 1:
        return None

    novo_norm = atual_norm.replace(old_norm, new_norm, 1)
    diff = unified_diff(path, atual_norm, novo_norm)
    return ProposedDiff(
        path=path,
        before=atual_norm,
        after=novo_norm,
        diff=diff,
        changed_lines=_count_changed_lines(diff),
        existed=True,
    )


def _diff_for_write_file(
    ctx: ToolContext, path: str, arguments: dict[str, Any]
) -> ProposedDiff | None:
    content = arguments.get("content")
    if content is None:
        return None

    try:
        existia = ctx.fs.exists(path)
        anterior = ctx.fs.read(path) if existia else ""
    except (PathEscapeError, FileTooLargeError, ValueError):
        return None

    diff = unified_diff(path, anterior, content)
    return ProposedDiff(
        path=path,
        before=anterior,
        after=content,
        diff=diff,
        changed_lines=_count_changed_lines(diff),
        existed=existia,
    )
