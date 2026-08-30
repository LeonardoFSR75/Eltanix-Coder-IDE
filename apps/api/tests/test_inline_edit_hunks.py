"""`agent/inline_edit_hunks.py` — split/apply de uma substituição inline em
hunks aceitáveis um a um (Cmd+K nível 2, Onda 1.3). Puro, sem I/O."""

from __future__ import annotations

from eltanix.agent.inline_edit_hunks import (
    apply_hunks,
    count_changed_lines,
    hunk_from_dict,
    hunk_to_dict,
    split_hunks,
)

BEFORE = "a\nb\nc\nd\ne\nf\ng\n"
# duas regiões trocadas, separadas por linhas iguais: b→B e (e,f)→(E,EE)
AFTER = "a\nB\nc\nd\nE\nEE\ng\n"


def test_split_finds_each_changed_block_in_order():
    hunks = split_hunks(BEFORE, AFTER)
    assert [h.id for h in hunks] == ["h1", "h2"]
    assert hunks[0].before_lines == ["b\n"]
    assert hunks[0].after_lines == ["B\n"]
    assert hunks[1].before_lines == ["e\n", "f\n"]
    assert hunks[1].after_lines == ["E\n", "EE\n"]
    # ordem preservada
    assert hunks[0].before_start < hunks[1].before_start


def test_split_no_change_yields_no_hunks():
    assert split_hunks(BEFORE, BEFORE) == []


def test_apply_all_hunks_reproduces_after():
    hunks = split_hunks(BEFORE, AFTER)
    assert apply_hunks(BEFORE, hunks, {h.id for h in hunks}) == AFTER


def test_apply_no_hunks_reproduces_before():
    hunks = split_hunks(BEFORE, AFTER)
    assert apply_hunks(BEFORE, hunks, set()) == BEFORE


def test_apply_subset_keeps_rejected_blocks_as_before():
    hunks = split_hunks(BEFORE, AFTER)
    # aceita só o segundo hunk
    out = apply_hunks(BEFORE, hunks, {"h2"})
    assert out == "a\nb\nc\nd\nE\nEE\ng\n"


def test_apply_subset_keeps_accepted_first_block_only():
    hunks = split_hunks(BEFORE, AFTER)
    out = apply_hunks(BEFORE, hunks, {"h1"})
    assert out == "a\nB\nc\nd\ne\nf\ng\n"


def test_hunk_dict_roundtrip():
    hunks = split_hunks(BEFORE, AFTER)
    again = [hunk_from_dict(hunk_to_dict(h)) for h in hunks]
    assert apply_hunks(BEFORE, again, {"h1", "h2"}) == AFTER


def test_count_changed_lines_only_counts_accepted():
    hunks = split_hunks(BEFORE, AFTER)
    # h1: 1 before + 1 after = 2 ; h2: 2 before + 2 after = 4
    assert count_changed_lines(hunks, {"h1"}) == 2
    assert count_changed_lines(hunks, {"h1", "h2"}) == 6
    assert count_changed_lines(hunks, set()) == 0


def test_pure_insertion_and_deletion():
    ins = split_hunks("x\ny\n", "x\nNEW\ny\n")
    assert ins[0].before_lines == [] and ins[0].after_lines == ["NEW\n"]
    assert apply_hunks("x\ny\n", ins, {"h1"}) == "x\nNEW\ny\n"
    assert apply_hunks("x\ny\n", ins, set()) == "x\ny\n"

    dele = split_hunks("x\nGONE\ny\n", "x\ny\n")
    assert dele[0].before_lines == ["GONE\n"] and dele[0].after_lines == []
    assert apply_hunks("x\nGONE\ny\n", dele, {"h1"}) == "x\ny\n"
