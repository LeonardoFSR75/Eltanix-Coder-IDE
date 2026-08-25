"""Config declarativa das regras de contexto: leitura de
`.eltanix/context_rules.yaml`.

Mesmo padrão de `agent/approval_policy_config.py`: leitura simples via
`yaml.safe_load` — a escrita, que precisa preservar comentários, fica em
`agent/context_rules_editor.py` via `ruamel.yaml`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from eltanix.agent.context_rules import ContextRulesConfig
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

_RELATIVE_PATH = Path(".eltanix") / "context_rules.yaml"


def load_context_rules(workspace_root: Path) -> ContextRulesConfig:
    """Lê `.eltanix/context_rules.yaml` do projeto (não do worktree da sessão —
    mesma raiz que `.eltanix/instructions.md`/`approval_policy.yaml`, ver
    `agent/runner.py::_load_custom_instructions`).

    Arquivo ausente, erro de leitura, YAML malformado ou dado que não valida
    contra `ContextRulesConfig` **sempre** degradam para uma config vazia
    (nenhuma regra) — nunca lança."""
    caminho = workspace_root / _RELATIVE_PATH
    try:
        raw = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ContextRulesConfig()
    except OSError as exc:
        log.warning("agent.context_rules.read_failed", error=str(exc)[:200])
        return ContextRulesConfig()

    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        log.warning("agent.context_rules.parse_failed", error=str(exc)[:200])
        return ContextRulesConfig()

    try:
        return ContextRulesConfig(**data)
    except ValidationError as exc:
        log.warning("agent.context_rules.validation_failed", error=str(exc)[:200])
        return ContextRulesConfig()
