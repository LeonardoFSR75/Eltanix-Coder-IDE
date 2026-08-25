"""`compute_proposed_diff`: diff a partir de argumentos propostos, antes de
qualquer escrita. Usado pela política de auto-aprovação e pela segunda
opinião automática — ambas dependem de nunca escrever nada aqui.
"""

from __future__ import annotations

import pytest

from eltanix.agent.tools import ToolContext
from eltanix.agent.tools.diffing import compute_proposed_diff
from eltanix.workspace.fs import WorkspaceFS


@pytest.fixture
def ctx(tmp_path):
    # `newline=""` evita a tradução de \n -> \r\n do modo texto do Windows —
    # sem isso, `write_file` (que não normaliza quebra de linha, diferente de
    # `edit_file`) leria \r\n de volta e as asserções abaixo, que comparam
    # string literal, quebrariam só no Windows.
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8", newline="")
    (tmp_path / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8", newline="")
    return ToolContext(
        session_id="teste",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
    )


def test_returns_none_for_tool_without_diff_concept(ctx):
    assert compute_proposed_diff(ctx, "run_command", {"command": "ls"}) is None


def test_returns_none_without_path(ctx):
    assert compute_proposed_diff(ctx, "edit_file", {}) is None


def test_edit_file_diff_never_writes_to_disk(ctx, tmp_path):
    proposed = compute_proposed_diff(
        ctx,
        "edit_file",
        {"path": "app.py", "old_text": "return 1", "new_text": "return 2"},
    )
    assert proposed is not None
    assert proposed.after == "def f():\n    return 2\n"
    assert "+    return 2" in proposed.diff
    assert "-    return 1" in proposed.diff
    assert proposed.changed_lines == 2
    # nada foi escrito — o arquivo no disco continua exatamente como estava
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"


def test_edit_file_returns_none_when_snippet_missing(ctx):
    proposed = compute_proposed_diff(
        ctx, "edit_file", {"path": "app.py", "old_text": "não existe", "new_text": "x"}
    )
    assert proposed is None


def test_edit_file_returns_none_for_ambiguous_snippet(ctx):
    # "x = 1" aparece duas vezes em dup.py — mesma regra que a própria
    # `edit_file` usa pra recusar a edição de verdade, ver files.py.
    proposed = compute_proposed_diff(
        ctx, "edit_file", {"path": "dup.py", "old_text": "x = 1", "new_text": "x = 2"}
    )
    assert proposed is None


def test_edit_file_returns_none_for_nonexistent_path(ctx):
    proposed = compute_proposed_diff(
        ctx, "edit_file", {"path": "nao_existe.py", "old_text": "a", "new_text": "b"}
    )
    assert proposed is None


def test_edit_file_returns_none_for_path_escape(ctx):
    proposed = compute_proposed_diff(
        ctx, "edit_file", {"path": "../fora.py", "old_text": "a", "new_text": "b"}
    )
    assert proposed is None


def test_write_file_diff_for_existing_file_never_writes_to_disk(ctx, tmp_path):
    proposed = compute_proposed_diff(
        ctx, "write_file", {"path": "app.py", "content": "novo conteúdo inteiro\n"}
    )
    assert proposed is not None
    assert proposed.existed is True
    assert proposed.before == "def f():\n    return 1\n"
    assert proposed.after == "novo conteúdo inteiro\n"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"


def test_write_file_diff_for_new_file_has_empty_before(ctx):
    proposed = compute_proposed_diff(
        ctx, "write_file", {"path": "novo.py", "content": "print(1)\n"}
    )
    assert proposed is not None
    assert proposed.existed is False
    assert proposed.before == ""
    assert proposed.after == "print(1)\n"


def test_write_file_returns_none_without_content(ctx):
    assert compute_proposed_diff(ctx, "write_file", {"path": "app.py"}) is None
