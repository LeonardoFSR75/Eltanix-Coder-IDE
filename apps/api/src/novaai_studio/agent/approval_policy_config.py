"""Config declarativa da política de auto-aprovação: leitura de
`.sicoobito/approval_policy.yaml`.

Mesmo padrão de `mcp/config.py`: leitura simples via `yaml.safe_load` — a
escrita, que precisa preservar comentários, fica em
`agent/approval_policy_editor.py` via `ruamel.yaml`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from sicoobito.agent.approval_policy import ApprovalPolicy
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

_RELATIVE_PATH = Path(".sicoobito") / "approval_policy.yaml"


def load_approval_policy(workspace_root: Path) -> ApprovalPolicy:
    """Lê `.sicoobito/approval_policy.yaml` do projeto (não do worktree da
    sessão — mesma raiz que `.sicoobito/instructions.md`, ver
    `agent/runner.py::_load_custom_instructions`).

    Arquivo ausente, erro de leitura, YAML malformado ou dado que não valida
    contra `ApprovalPolicy` **sempre** degradam para uma política vazia —
    idêntico ao comportamento de hoje (nenhuma regra = tudo pausa como
    sempre). Nunca lança."""
    caminho = workspace_root / _RELATIVE_PATH
    try:
        raw = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ApprovalPolicy()
    except OSError as exc:
        log.warning("agent.approval_policy.read_failed", error=str(exc)[:200])
        return ApprovalPolicy()

    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        log.warning("agent.approval_policy.parse_failed", error=str(exc)[:200])
        return ApprovalPolicy()

    try:
        return ApprovalPolicy(**data)
    except ValidationError as exc:
        log.warning("agent.approval_policy.validation_failed", error=str(exc)[:200])
        return ApprovalPolicy()
