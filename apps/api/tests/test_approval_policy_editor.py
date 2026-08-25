"""Round-trip de `.eltanix/approval_policy.yaml` via `approval_policy_editor`."""

from __future__ import annotations

import pytest

from eltanix.agent import approval_policy_editor as editor
from eltanix.agent.approval_policy_config import load_approval_policy


def test_load_on_missing_file_returns_defaults(tmp_path):
    data = editor.load(tmp_path)
    assert data["version"] == 1
    assert data["second_opinion"] is False
    assert list(data["rules"]) == []


def test_add_rule_then_dump_is_readable_by_load_approval_policy(tmp_path):
    data = editor.load(tmp_path)
    editor.add_rule(
        data,
        {
            "kind": "edit_path_glob",
            "tools": ["edit_file"],
            "path_glob": "*.md",
            "max_changed_lines": 15,
        },
    )
    editor.dump(tmp_path, data)

    policy = load_approval_policy(tmp_path)
    assert len(policy.rules) == 1
    assert policy.rules[0].path_glob == "*.md"
    assert policy.rules[0].max_changed_lines == 15


def test_remove_rule_by_index(tmp_path):
    data = editor.load(tmp_path)
    editor.add_rule(data, {"kind": "exec_command_prefix", "allowed_prefixes": ["npm test"]})
    editor.add_rule(data, {"kind": "exec_command_prefix", "allowed_prefixes": ["pytest"]})
    editor.remove_rule(data, 0)
    editor.dump(tmp_path, data)

    policy = load_approval_policy(tmp_path)
    assert len(policy.rules) == 1
    assert policy.rules[0].allowed_prefixes == ["pytest"]


def test_remove_rule_out_of_range_raises(tmp_path):
    data = editor.load(tmp_path)
    with pytest.raises(IndexError):
        editor.remove_rule(data, 0)


def test_set_second_opinion_toggles_flag(tmp_path):
    data = editor.load(tmp_path)
    editor.set_second_opinion(data, True)
    editor.dump(tmp_path, data)

    policy = load_approval_policy(tmp_path)
    assert policy.second_opinion is True


def test_round_trip_preserves_comments(tmp_path):
    caminho = editor.policy_path(tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        "# comentário importante\nversion: 1\nsecond_opinion: false\nrules: []\n",
        encoding="utf-8",
    )

    data = editor.load(tmp_path)
    editor.set_second_opinion(data, True)
    editor.dump(tmp_path, data)

    conteudo = caminho.read_text(encoding="utf-8")
    assert "# comentário importante" in conteudo
