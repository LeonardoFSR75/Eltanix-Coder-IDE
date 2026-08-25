"""Política de auto-aprovação — opt-in, por projeto.

Não é um DSL: uma lista curta de regras tipadas, cada uma restrita ao ponto
de nunca poder aprovar por engano algo fora do que descreve explicitamente.
Qualquer erro ao avaliar uma regra (glob inválido, argumento ausente, caminho
fora do workspace) conta como "essa regra não casou" — nunca como "aprovado
por omissão". `evaluate_policy()` é chamado por `agent/graph.py::approve()`
antes do `interrupt()`; o que ela não aprovar continua pausando exatamente
como hoje.
"""

from __future__ import annotations

import fnmatch
import shlex
from typing import Literal

from pydantic import BaseModel, Field

from sicoobito.agent.state import PendingApproval
from sicoobito.agent.tools.base import ToolContext
from sicoobito.agent.tools.diffing import compute_proposed_diff
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Qualquer um destes caracteres no comando inteiro derruba o match de
# `ExecCommandRule`, mesmo que os tokens iniciais batam com um prefixo
# permitido — "npm test" como prefixo não pode aprovar "npm test && rm -rf /".
# Esta é a propriedade de segurança central da regra, não o prefixo em si.
# "\n" precisa estar aqui: `shlex.split` trata quebra de linha como espaço
# comum (então "npm test\nrm -rf /" tokeniza igual a "npm test rm -rf /" e
# bateria no prefixo "npm test"), mas `sh -c` — que é quem de fato roda o
# comando no sandbox — trata "\n" como separador de comando, igual a ";".
_DANGEROUS_COMMAND_CHARS = (";", "&", "|", "`", "$(", ">", "<", "\n")


class EditPathRule(BaseModel):
    kind: Literal["edit_path_glob"] = "edit_path_glob"
    tools: list[Literal["edit_file", "write_file"]] = Field(default_factory=lambda: ["edit_file"])
    # Glob simples (fnmatch: *, ?, [seq]) sobre o caminho relativo ao
    # workspace — não trata "/" como especial (mesmo espírito "sem DSL": um
    # glob mais expressivo é complexidade que essa regra não precisa).
    path_glob: str
    max_changed_lines: int = 20


class ExecCommandRule(BaseModel):
    kind: Literal["exec_command_prefix"] = "exec_command_prefix"
    allowed_prefixes: list[str]


class ApprovalPolicy(BaseModel):
    version: int = 1
    # Gate da segunda opinião automática (Fase C) — vive aqui e não numa config
    # própria porque as duas features compartilham o mesmo arquivo por projeto.
    second_opinion: bool = False
    rules: list[EditPathRule | ExecCommandRule] = Field(default_factory=list)


def _matches_edit_path_rule(rule: EditPathRule, ctx: ToolContext, pending: PendingApproval) -> bool:
    if pending["tool"] not in rule.tools:
        return False

    path = pending["arguments"].get("path")
    if not path:
        return False
    normalized = str(path).replace("\\", "/")
    if not fnmatch.fnmatch(normalized, rule.path_glob):
        return False

    proposed = compute_proposed_diff(ctx, pending["tool"], pending["arguments"])
    if proposed is None:
        # Sem diff calculável (arquivo ambíguo, fora do workspace, argumento
        # faltando) — não há como confirmar o tamanho da mudança, então a
        # regra não casa. Fail closed.
        return False
    return proposed.changed_lines <= rule.max_changed_lines


def _matches_exec_command_rule(rule: ExecCommandRule, pending: PendingApproval) -> bool:
    if pending["tool"] != "run_command":
        return False

    command = pending["arguments"].get("command")
    if not command or not isinstance(command, str):
        return False
    if any(char in command for char in _DANGEROUS_COMMAND_CHARS):
        return False

    try:
        tokens = shlex.split(command)
    except ValueError:
        # Aspas desbalanceadas etc. — comando malformado não casa com nada.
        return False

    # Wrappers explícitos de shell (bash, sh, zsh, powershell, cmd, pwsh) são
    # sempre rejeitados, mesmo quando o prefixo permitido parece ser "npm test".
    # O runtime real aqui é o shell que chama o comando, não o programa que foi
    # permitido; a regra é fail-closed e não aceita eufemismos de shell.
    if tokens and tokens[0].lower() in {"bash", "sh", "zsh", "powershell", "pwsh", "cmd"}:
        return False
    if tokens and len(tokens) >= 2 and tokens[0].lower() in {"sudo"}:
        return False

    for allowed in rule.allowed_prefixes:
        try:
            allowed_tokens = shlex.split(allowed)
        except ValueError:
            continue
        if allowed_tokens and tokens[: len(allowed_tokens)] == allowed_tokens:
            return True
    return False


def _describe(rule: EditPathRule | ExecCommandRule) -> str:
    if isinstance(rule, EditPathRule):
        return f"edição em {rule.path_glob!r} com até {rule.max_changed_lines} linha(s) alterada(s)"
    return f"comando de shell com prefixo permitido ({', '.join(rule.allowed_prefixes)})"


def evaluate_policy(
    policy: ApprovalPolicy, ctx: ToolContext, pending: PendingApproval
) -> str | None:
    """Retorna a descrição da primeira regra que casar (== auto-aprovar),
    ou `None` se nenhuma casar — inclusive quando a própria avaliação de uma
    regra lança exceção (glob malformado, etc.): a exceção é logada e tratada
    como não-match daquela regra específica, nunca propaga."""
    for rule in policy.rules:
        try:
            if isinstance(rule, EditPathRule):
                matched = _matches_edit_path_rule(rule, ctx, pending)
            else:
                matched = _matches_exec_command_rule(rule, pending)
        except Exception as exc:
            log.warning(
                "agent.approval_policy.rule_eval_failed",
                rule=rule.kind,
                error=str(exc)[:200],
            )
            continue
        if matched:
            return _describe(rule)
    return None
