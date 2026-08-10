"""Política de auto-aprovação: `evaluate_policy` decide se uma ação WRITE/EXEC
pendente casa com alguma regra explícita — nunca aprova por omissão, e
qualquer erro de avaliação vira "essa regra não casou", não exceção.

`ExecCommandRule` tem uma suíte adversarial dedicada: o bloqueio de
caracteres perigosos é a propriedade de segurança central da regra, então
cada um deles precisa de um teste próprio, não só um caso genérico.
"""

from __future__ import annotations

import pytest

from sicoobito.agent.approval_policy import (
    ApprovalPolicy,
    EditPathRule,
    ExecCommandRule,
    evaluate_policy,
)
from sicoobito.agent.tools import ToolContext
from sicoobito.workspace.fs import WorkspaceFS


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "README.md").write_text("linha 1\nlinha 2\n", encoding="utf-8", newline="")
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8", newline="")
    return ToolContext(
        session_id="teste",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
    )


def _pending(tool: str, arguments: dict) -> dict:
    return {
        "tool_call_id": "call_1",
        "tool": tool,
        "risk": "write" if tool != "run_command" else "exec",
        "arguments": arguments,
        "summary": f"{tool}(...)",
    }


# ── ApprovalPolicy vazia: comportamento idêntico ao de hoje ─────────────────


def test_empty_policy_never_auto_approves(ctx):
    policy = ApprovalPolicy()
    pending = _pending("edit_file", {"path": "README.md", "old_text": "linha 1", "new_text": "x"})
    assert evaluate_policy(policy, ctx, pending) is None


# ── EditPathRule ─────────────────────────────────────────────────────────────


def test_edit_path_rule_matches_within_glob_and_line_limit(ctx):
    policy = ApprovalPolicy(
        rules=[EditPathRule(path_glob="*.md", max_changed_lines=5)]
    )
    pending = _pending(
        "edit_file", {"path": "README.md", "old_text": "linha 1", "new_text": "linha um"}
    )
    resultado = evaluate_policy(policy, ctx, pending)
    assert resultado is not None
    assert "README.md" in resultado or "*.md" in resultado


def test_edit_path_rule_does_not_match_wrong_tool(ctx):
    policy = ApprovalPolicy(rules=[EditPathRule(tools=["write_file"], path_glob="*.md")])
    pending = _pending(
        "edit_file", {"path": "README.md", "old_text": "linha 1", "new_text": "x"}
    )
    assert evaluate_policy(policy, ctx, pending) is None


def test_edit_path_rule_does_not_match_outside_glob(ctx):
    policy = ApprovalPolicy(rules=[EditPathRule(path_glob="*.md")])
    pending = _pending("edit_file", {"path": "app.py", "old_text": "return 1", "new_text": "x"})
    assert evaluate_policy(policy, ctx, pending) is None


def test_edit_path_rule_does_not_match_when_diff_exceeds_max_lines(ctx):
    policy = ApprovalPolicy(rules=[EditPathRule(path_glob="*.md", max_changed_lines=1)])
    pending = _pending(
        "edit_file",
        {"path": "README.md", "old_text": "linha 1\nlinha 2", "new_text": "a\nb\nc"},
    )
    assert evaluate_policy(policy, ctx, pending) is None


def test_edit_path_rule_fails_closed_when_diff_cannot_be_computed(ctx):
    # old_text não existe em README.md -> compute_proposed_diff devolve None
    # -> a regra não pode confirmar o tamanho da mudança -> não casa.
    policy = ApprovalPolicy(rules=[EditPathRule(path_glob="*.md", max_changed_lines=999)])
    pending = _pending(
        "edit_file", {"path": "README.md", "old_text": "não existe", "new_text": "x"}
    )
    assert evaluate_policy(policy, ctx, pending) is None


def test_edit_path_rule_matches_write_file_when_listed(ctx):
    policy = ApprovalPolicy(
        rules=[EditPathRule(tools=["write_file"], path_glob="*.md", max_changed_lines=50)]
    )
    pending = _pending("write_file", {"path": "README.md", "content": "conteúdo novo\n"})
    assert evaluate_policy(policy, ctx, pending) is not None


# ── ExecCommandRule: casos normais ──────────────────────────────────────────


def test_exec_command_rule_matches_exact_prefix(ctx):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("run_command", {"command": "npm test"})
    assert evaluate_policy(policy, ctx, pending) is not None


def test_exec_command_rule_matches_prefix_with_extra_args(ctx):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("run_command", {"command": "npm test --watch=false"})
    assert evaluate_policy(policy, ctx, pending) is not None


def test_exec_command_rule_does_not_match_different_command(ctx):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("run_command", {"command": "npm run build"})
    assert evaluate_policy(policy, ctx, pending) is None


def test_exec_command_rule_does_not_match_non_exec_tool(ctx):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("edit_file", {"path": "README.md", "old_text": "a", "new_text": "b"})
    assert evaluate_policy(policy, ctx, pending) is None


def test_exec_command_rule_prefix_does_not_match_partial_token():
    # "npm te" não é prefixo de tokens de "npm test" — token inteiro, não
    # substring, senão "npm te" aprovaria "npm terminate-everything".
    from sicoobito.agent.approval_policy import _matches_exec_command_rule

    rule = ExecCommandRule(allowed_prefixes=["npm te"])
    pending = _pending("run_command", {"command": "npm test"})
    assert _matches_exec_command_rule(rule, pending) is False


# ── ExecCommandRule: suíte adversarial de caracteres perigosos ──────────────
# Cada um destes teria, sem o bloqueio, deixado passar um comando adicional
# não coberto pelo prefixo permitido — a lista espelha o que a docstring do
# módulo promete bloquear.


@pytest.mark.parametrize(
    "malicious_command",
    [
        "npm test; rm -rf /",
        "npm test && rm -rf /",
        "npm test || rm -rf /",
        "npm test | tee /etc/passwd",
        "npm test `rm -rf /`",
        "npm test $(rm -rf /)",
        "npm test > /etc/passwd",
        "npm test < /etc/shadow",
    ],
)
def test_exec_command_rule_rejects_dangerous_characters_even_with_valid_prefix(
    ctx, malicious_command
):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("run_command", {"command": malicious_command})
    assert evaluate_policy(policy, ctx, pending) is None


def test_exec_command_rule_rejects_malformed_shell_quoting(ctx):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("run_command", {"command": 'npm test "unbalanced'})
    assert evaluate_policy(policy, ctx, pending) is None


def test_exec_command_rule_rejects_empty_command(ctx):
    policy = ApprovalPolicy(rules=[ExecCommandRule(allowed_prefixes=["npm test"])])
    pending = _pending("run_command", {"command": ""})
    assert evaluate_policy(policy, ctx, pending) is None


# ── Múltiplas regras e falha de avaliação (fail closed) ─────────────────────


def test_evaluate_policy_tries_rules_in_order_and_returns_first_match(ctx):
    policy = ApprovalPolicy(
        rules=[
            EditPathRule(path_glob="*.py", max_changed_lines=5),
            EditPathRule(path_glob="*.md", max_changed_lines=5),
        ]
    )
    pending = _pending(
        "edit_file", {"path": "README.md", "old_text": "linha 1", "new_text": "x"}
    )
    resultado = evaluate_policy(policy, ctx, pending)
    assert resultado is not None
    assert "*.md" in resultado


def test_evaluate_policy_swallows_exception_from_a_single_rule(ctx, monkeypatch):
    # Uma regra que explode na avaliação não deve derrubar as outras nem
    # propagar — só conta como "essa regra não casou".
    import sicoobito.agent.approval_policy as approval_policy_module

    def _broken(rule, ctx, pending):
        raise RuntimeError("boom")

    monkeypatch.setattr(approval_policy_module, "_matches_edit_path_rule", _broken)

    policy = ApprovalPolicy(rules=[EditPathRule(path_glob="*.md", max_changed_lines=5)])
    pending = _pending(
        "edit_file", {"path": "README.md", "old_text": "linha 1", "new_text": "x"}
    )
    assert evaluate_policy(policy, ctx, pending) is None
