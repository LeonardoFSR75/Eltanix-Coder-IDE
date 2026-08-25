"""Edição estrutural de `.novaai_studio/approval_policy.yaml` preservando
comentários — mesmo padrão de `mcp/config_editor.py` (round-trip via
`ruamel.yaml`).

Sem rota de API nesta fase: o arquivo é editável à mão por enquanto. Estas
funções existem para uma futura tela de configuração não precisar reinventar
o parsing — só ligar um botão a `add_rule`/`remove_rule`/`set_second_opinion`.
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

_RELATIVE_PATH = Path(".novaai_studio") / "approval_policy.yaml"


def policy_path(workspace_root: Path) -> Path:
    return workspace_root / _RELATIVE_PATH


def load(workspace_root: Path) -> CommentedMap:
    caminho = policy_path(workspace_root)
    if not caminho.exists():
        data = CommentedMap()
    else:
        with caminho.open("r", encoding="utf-8") as fh:
            data = _yaml.load(fh)
        if data is None:
            data = CommentedMap()

    data.setdefault("version", 1)
    data.setdefault("second_opinion", False)
    if data.get("rules") is None:
        data["rules"] = CommentedSeq()
    return data


def dump(workspace_root: Path, data: CommentedMap) -> None:
    caminho = policy_path(workspace_root)
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


def set_second_opinion(data: CommentedMap, enabled: bool) -> None:
    data["second_opinion"] = enabled
