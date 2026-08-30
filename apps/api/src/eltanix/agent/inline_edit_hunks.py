"""Divisão de uma substituição inline (Cmd+K nível 2, Onda 1.3) em *hunks*
independentes, para o usuário aceitar/rejeitar cada bloco de mudança.

Puro: opera sobre `before`/`after` já resolvidos (o `ProposedDiff` de
`agent/tools/diffing.py`), sem I/O. `apply_hunks` reconstrói o texto final
aplicando só os hunks aceitos — um hunk rejeitado mantém as linhas do
`before`. `tests/test_inline_edit_hunks.py` exercita tudo aqui.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

# Linhas de contexto (iguais) mostradas em volta de cada hunk na revisão.
_CONTEXT = 2


@dataclass(slots=True)
class Hunk:
    id: str
    # Índice 0-based, na lista de linhas do `before`, onde o bloco trocado começa.
    before_start: int
    before_lines: list[str]
    after_lines: list[str]
    context_before: list[str]
    context_after: list[str]


def split_hunks(before: str, after: str, *, context: int = _CONTEXT) -> list[Hunk]:
    """Cada opcode não-`equal` do `SequenceMatcher` vira um hunk, na ordem em
    que aparecem no arquivo. Hunks não se sobrepõem."""
    b = before.splitlines(keepends=True)
    a = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, b, a, autojunk=False)

    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append(
            Hunk(
                id=f"h{len(hunks) + 1}",
                before_start=i1,
                before_lines=b[i1:i2],
                after_lines=a[j1:j2],
                context_before=b[max(0, i1 - context) : i1],
                context_after=b[i2 : i2 + context],
            )
        )
    return hunks


def apply_hunks(before: str, hunks: list[Hunk], accepted_ids: set[str]) -> str:
    """Reconstrói o texto: regiões iguais passam direto; hunk aceito usa
    `after_lines`, hunk rejeitado mantém `before_lines`."""
    b = before.splitlines(keepends=True)
    out: list[str] = []
    cursor = 0
    for hunk in sorted(hunks, key=lambda h: h.before_start):
        out.extend(b[cursor : hunk.before_start])
        end = hunk.before_start + len(hunk.before_lines)
        if hunk.id in accepted_ids:
            out.extend(hunk.after_lines)
        else:
            out.extend(b[hunk.before_start : end])
        cursor = end
    out.extend(b[cursor:])
    return "".join(out)


def hunk_to_dict(hunk: Hunk) -> dict:
    return {
        "id": hunk.id,
        "before_start": hunk.before_start,
        "before_lines": hunk.before_lines,
        "after_lines": hunk.after_lines,
        "context_before": hunk.context_before,
        "context_after": hunk.context_after,
    }


def hunk_from_dict(data: dict) -> Hunk:
    return Hunk(
        id=str(data["id"]),
        before_start=int(data["before_start"]),
        before_lines=list(data.get("before_lines") or []),
        after_lines=list(data.get("after_lines") or []),
        context_before=list(data.get("context_before") or []),
        context_after=list(data.get("context_after") or []),
    )


def count_changed_lines(hunks: list[Hunk], accepted_ids: set[str]) -> int:
    return sum(len(h.before_lines) + len(h.after_lines) for h in hunks if h.id in accepted_ids)
