"""Edição estrutural de `config/providers.yaml` preservando comentários.

Mesmo padrão de `routes_editor.py` (round-trip via `ruamel.yaml`), mas mais
simples num ponto: ao contrário de `routes.yaml`, `providers.yaml` não tem
comentário de rodapé preso à última entrada — a lista `providers:` termina
limpa depois do último item. Por isso `append_models` só dá `append` na
`CommentedSeq`, sem o truque de posicionamento que `routes_editor.upsert_profile`
precisa usar.
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

# Ordem de campo estável na entrada gravada — não é a ordem de inserção do
# dict de origem, que dependeria da ordem dos atributos do request da API.
_FIELD_ORDER = (
    "id",
    "provider",
    "model",
    "deployment",
    "endpoint",
    "mode",
    "context_window",
    "tags",
    "capabilities",
    "enabled",
)


def load(providers_file: Path) -> CommentedMap:
    with providers_file.open("r", encoding="utf-8") as fh:
        return _yaml.load(fh)


def dump(providers_file: Path, data: CommentedMap) -> None:
    with providers_file.open("w", encoding="utf-8") as fh:
        _yaml.dump(data, fh)


def append_models(data: CommentedMap, entries: list[dict[str, Any]]) -> None:
    """Acrescenta entradas ao fim de `providers:`. Nunca sobrescreve uma existente."""
    providers: CommentedSeq = data["providers"]
    for entry in entries:
        node = CommentedMap()
        for key in _FIELD_ORDER:
            value = entry.get(key)
            if value is not None:
                node[key] = value
        providers.append(node)
