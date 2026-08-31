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

Perfis existentes têm os campos (`strategy`/`weights`/`models`) editados
in-place no `CommentedMap`/`CommentedSeq` já carregados, nunca substituídos
por objetos novos: pelo mesmo motivo acima, o comentário de bloco de um
perfil qualquer fica preso ao último nó-folha do perfil ANTERIOR (o último
índice da sua lista `models`). Um `profiles[name] = novo_node` apagaria esse
comentário do perfil seguinte, e um `CommentedMap(weights)` do zero perderia
a formatação de escalares que nem mudaram (`0.30` vira `0.3`).
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

    if name in profiles:
        _update_profile_fields(profiles[name], strategy=strategy, models=models, weights=weights)
        return

    node = CommentedMap()
    node["strategy"] = strategy
    if weights:
        node["weights"] = CommentedMap(weights)
    node["models"] = CommentedSeq(list(models))

    pos = max(len(profiles) - 1, 0)
    profiles.insert(pos, name, node)


def _update_profile_fields(
    node: CommentedMap,
    *,
    strategy: str,
    models: list[str],
    weights: dict[str, float] | None,
) -> None:
    """Atualiza os campos de um perfil existente sem trocar o `CommentedMap`
    do nó. Substituir `profiles[name]` inteiro desloca o comentário do
    PRÓXIMO perfil (o ruamel prende comentários de bloco à posição do nó
    anterior em `profiles`, não à chave) e reformata escalares que nem
    mudaram (`0.30` perde o zero à direita ao ser recriado do zero).
    """
    node["strategy"] = strategy
    _update_weights(node, weights)
    _update_models(node, models)


def _update_weights(node: CommentedMap, weights: dict[str, float] | None) -> None:
    if not weights:
        if "weights" in node:
            del node["weights"]
        return

    existing = node.get("weights")
    if not isinstance(existing, CommentedMap):
        node["weights"] = CommentedMap(weights)
        return

    for key in [k for k in existing if k not in weights]:
        del existing[key]
    for key, value in weights.items():
        if key in existing and float(existing[key]) == float(value):
            continue
        existing[key] = value


def _update_models(node: CommentedMap, models: list[str]) -> None:
    existing = node.get("models")
    if not isinstance(existing, CommentedSeq):
        node["models"] = CommentedSeq(list(models))
        return
    if list(existing) == list(models):
        return

    # O comentário de bloco do PRÓXIMO perfil fica preso, pelo ruamel, ao
    # último índice desta `CommentedSeq` (`ca.items[len(existing) - 1]`) —
    # não a um atributo de "fim de bloco" da sequência ou do `CommentedMap`
    # do perfil. Truncar/reescrever a lista sem realocar essa entrada faz o
    # comentário apontar para um índice que deixou de existir e ele some no
    # dump. Por isso o comentário do último item é salvo e reanexado ao novo
    # último índice antes de trocar o conteúdo.
    trailing_comment = existing.ca.items.pop(len(existing) - 1, None) if existing else None

    del existing[:]
    existing.extend(models)

    if trailing_comment is not None and existing:
        existing.ca.items[len(existing) - 1] = trailing_comment


def delete_profile(data: CommentedMap, name: str) -> None:
    del data["profiles"][name]
