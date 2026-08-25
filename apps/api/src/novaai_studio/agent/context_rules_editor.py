"""Edição estrutural de `.novaai_studio/context_rules.yaml` preservando
comentários — mesmo padrão de `agent/approval_policy_editor.py`/
`mcp/config_editor.py` (round-trip via `ruamel.yaml`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.width = 4096

_RELATIVE_PATH = Path(".novaai_studio") / "context_rules.yaml"


def rules_path(workspace_root: Path) -> Path:
    return workspace_root / _RELATIVE_PATH


def load(workspace_root: Path) -> CommentedMap:
    caminho = rules_path(workspace_root)
    if not caminho.exists():
        data = CommentedMap()
    else:
        with caminho.open("r", encoding="utf-8") as fh:
            data = _yaml.load(fh)
        if data is None:
            data = CommentedMap()

    data.setdefault("version", 1)
    if data.get("rules") is None:
        data["rules"] = CommentedSeq()
    return data


def dump(workspace_root: Path, data: CommentedMap) -> None:
    caminho = rules_path(workspace_root)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as fh:
        _yaml.dump(data, fh)


def add_rule(data: CommentedMap, rule: dict[str, Any]) -> None:
    rules: CommentedSeq = data["rules"]
    node = CommentedMap()
    for key, value in rule.items():
        if value is not None:
            node[key] = value
    rules.append(node)


def remove_rule(data: CommentedMap, index: int) -> None:
    rules: CommentedSeq = data["rules"]
    if index < 0 or index >= len(rules):
        raise IndexError(f"índice de regra fora do intervalo: {index}")
    del rules[index]
