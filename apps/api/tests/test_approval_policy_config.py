"""`load_approval_policy`: sempre degrada para uma política vazia — arquivo
ausente, YAML malformado ou dado inválido nunca devem impedir a sessão de
começar (mesmo espírito de `_load_custom_instructions`)."""

from __future__ import annotations

from novaai_studio.agent.approval_policy import ApprovalPolicy
from novaai_studio.agent.approval_policy_config import load_approval_policy


def test_missing_file_returns_empty_policy(tmp_path):
    policy = load_approval_policy(tmp_path)
    assert policy == ApprovalPolicy()
    assert policy.rules == []


def test_valid_yaml_parses_rules(tmp_path):
    diretorio = tmp_path / ".novaai_studio"
    diretorio.mkdir()
    (diretorio / "approval_policy.yaml").write_text(
        """
version: 1
second_opinion: true
rules:
  - kind: edit_path_glob
    tools: [edit_file]
    path_glob: "*.md"
    max_changed_lines: 10
  - kind: exec_command_prefix
    allowed_prefixes: ["npm test", "pytest"]
""",
        encoding="utf-8",
    )
    policy = load_approval_policy(tmp_path)
    assert policy.second_opinion is True
    assert len(policy.rules) == 2
    assert policy.rules[0].kind == "edit_path_glob"
    assert policy.rules[1].kind == "exec_command_prefix"


def test_malformed_yaml_degrades_to_empty_policy(tmp_path):
    diretorio = tmp_path / ".novaai_studio"
    diretorio.mkdir()
    (diretorio / "approval_policy.yaml").write_text(
        "rules: [this is not: valid: yaml:", encoding="utf-8"
    )
    policy = load_approval_policy(tmp_path)
    assert policy == ApprovalPolicy()


def test_invalid_data_degrades_to_empty_policy(tmp_path):
    diretorio = tmp_path / ".novaai_studio"
    diretorio.mkdir()
    (diretorio / "approval_policy.yaml").write_text(
        """
rules:
  - kind: edit_path_glob
    max_changed_lines: "não é um número"
""",
        encoding="utf-8",
    )
    policy = load_approval_policy(tmp_path)
    assert policy == ApprovalPolicy()


def test_empty_file_returns_empty_policy(tmp_path):
    diretorio = tmp_path / ".novaai_studio"
    diretorio.mkdir()
    (diretorio / "approval_policy.yaml").write_text("", encoding="utf-8")
    policy = load_approval_policy(tmp_path)
    assert policy == ApprovalPolicy()
