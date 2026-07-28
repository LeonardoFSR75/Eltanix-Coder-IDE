"""Edição estrutural de `config/routes.yaml` preservando comentários.

`catalog.py` só *lê* o arquivo (via `yaml.safe_load`, mais simples e já
testado). Este módulo existe à parte porque *escrever* de volta sem apagar a
documentação inline exige round-trip (`ruamel.yaml`), uma dependência mais
pesada que não faz sentido puxar para o caminho de leitura.

Perfis novos são sempre inseridos imediatamente antes da última chave já
existente em `profiles`, nunca ao final: o parser do ruamel prende o
comentário de rodapé do arquivo (ex.: "# Resiliência aplicada...") ao último
nó-folha do último perfil, não à seção `profiles` como um todo. Um `dict[key]
= valor` comum manteria esse comentário fisicamente entre o perfil antigo e o
novo — ainda válido como YAML, mas enganoso para quem lê o arquivo depois.
Inserir antes da última chave deixa o rodapé grudado onde sempre esteve.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.width = 4096


def load(routes_file: Path) -> CommentedMap:
    with routes_file.open("r", encoding="utf-8") as fh:
        return _yaml.load(fh)


def dump(routes_file: Path, data: CommentedMap) -> None:
    with routes_file.open("w", encoding="utf-8") as fh:
        _yaml.dump(data, fh)


def set_default_profile(data: CommentedMap, profile: str) -> None:
    data["default_profile"] = profile


def upsert_profile(
    data: CommentedMap,
    name: str,
    *,
    strategy: str,
    models: list[str],
    weights: dict[str, float] | None,
) -> None:
    profiles: CommentedMap = data["profiles"]

    node = CommentedMap()
    node["strategy"] = strategy
    if weights:
        node["weights"] = CommentedMap(weights)
    node["models"] = CommentedSeq(list(models))

    if name in profiles:
        profiles[name] = node
    else:
        pos = max(len(profiles) - 1, 0)
        profiles.insert(pos, name, node)


def delete_profile(data: CommentedMap, name: str) -> None:
    del data["profiles"][name]
