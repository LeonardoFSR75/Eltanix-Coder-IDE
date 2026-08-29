"""`resolve_edit` — núcleo compartilhado entre `edit_file` (escrita) e
`diffing._diff_for_edit_file` (preview). Antes essa lógica vivia duplicada e o
preview ficava para trás da escrita a cada ajuste na heurística de casamento.
"""

from __future__ import annotations

import pytest

from eltanix.agent.tools.files import (
    EditAmbiguousError,
    EditNotFoundError,
    resolve_edit,
)

BASE = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"


def test_exact_match_applies_the_swap():
    r = resolve_edit(BASE, "    return 1", "    return 42")
    assert "return 42" in r.after
    assert r.before == BASE
    assert r.line_ending == "\n"


def test_missing_snippet_raises_not_found():
    with pytest.raises(EditNotFoundError):
        resolve_edit(BASE, "    return 999", "x")


def test_ambiguous_snippet_raises_with_count():
    with pytest.raises(EditAmbiguousError) as exc:
        resolve_edit("x = 1\nx = 1\n", "x = 1", "x = 2")
    assert exc.value.ocorrencias == 2


def test_crlf_file_is_matched_with_lf_snippet_and_line_ending_preserved():
    crlf = BASE.replace("\n", "\r\n")
    r = resolve_edit(crlf, "    return 1", "    return 42")
    # before/after saem normalizados para \n; quem grava reconverte via line_ending
    assert "\r\n" not in r.after
    assert r.line_ending == "\r\n"


def test_fuzzy_fallback_matches_ignoring_trailing_whitespace_when_allowed():
    # arquivo tem espaço no fim da linha; o modelo mandou sem
    sujo = "a = 1   \nb = 2\n"
    r = resolve_edit(sujo, "a = 1\nb = 2", "a = 1\nb = 3", allow_fuzzy=True)
    assert "b = 3" in r.after


def test_preview_path_disables_fuzzy_and_gets_not_found():
    sujo = "a = 1   \nb = 2\n"
    with pytest.raises(EditNotFoundError):
        resolve_edit(sujo, "a = 1\nb = 2", "a = 1\nb = 3", allow_fuzzy=False)


def test_fuzzy_fallback_still_refuses_when_it_would_be_ambiguous():
    arquivo = "a = 1\nx\na = 1\ny\n"
    # `old_text` do modelo tem espaço no fim -> casamento exato falha (count 0);
    # o rstrip casaria as DUAS linhas -> não promove, continua não encontrado.
    with pytest.raises(EditNotFoundError):
        resolve_edit(arquivo, "a = 1   ", "a = 2", allow_fuzzy=True)
