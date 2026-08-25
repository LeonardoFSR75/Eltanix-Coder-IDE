"""Edição estrutural de `config/mcp.yaml` preservando comentários.

Mesmo padrão de `router/providers_editor.py` (round-trip via `ruamel.yaml`),
mas `servers` é uma lista, não um mapa por nome como `routes.yaml::profiles`
— upsert/delete precisam varrer procurando `name`.
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

_STDIO_FIELDS = (
    "name",
    "transport",
    "command",
    "args",
    "env",
    "enabled",
    "trust_annotations",
    "tool_overrides",
)
_HTTP_FIELDS = (
    "name",
    "transport",
    "url",
    "headers",
    "enabled",
    "trust_annotations",
    "tool_overrides",
)


def load(mcp_file: Path) -> CommentedMap:
    with mcp_file.open("r", encoding="utf-8") as fh:
        data = _yaml.load(fh)
    if data is None:
        data = CommentedMap()
    if data.get("servers") is None:
        data["servers"] = CommentedSeq()
    return data


def dump(mcp_file: Path, data: CommentedMap) -> None:
    with mcp_file.open("w", encoding="utf-8") as fh:
        _yaml.dump(data, fh)


def _build_node(entry: dict[str, Any]) -> CommentedMap:
    fields = _STDIO_FIELDS if entry.get("transport") == "stdio" else _HTTP_FIELDS
    node = CommentedMap()
    for key in fields:
        value = entry.get(key)
        if value is not None:
            node[key] = value
    return node


def _find_index(servers: CommentedSeq, name: str) -> int | None:
    for i, item in enumerate(servers):
        if item.get("name") == name:
            return i
    return None


def append_server(data: CommentedMap, entry: dict[str, Any]) -> None:
    servers: CommentedSeq = data["servers"]
    if _find_index(servers, entry["name"]) is not None:
        raise ValueError(f"servidor já existe: {entry['name']}")
    servers.append(_build_node(entry))


def update_server(data: CommentedMap, name: str, entry: dict[str, Any]) -> None:
    servers: CommentedSeq = data["servers"]
    idx = _find_index(servers, name)
    if idx is None:
        raise KeyError(f"servidor não encontrado: {name}")
    servers[idx] = _build_node(entry)


def delete_server(data: CommentedMap, name: str) -> None:
    servers: CommentedSeq = data["servers"]
    idx = _find_index(servers, name)
    if idx is None:
        raise KeyError(f"servidor não encontrado: {name}")
    del servers[idx]


def set_enabled(data: CommentedMap, name: str, enabled: bool) -> None:
    servers: CommentedSeq = data["servers"]
    idx = _find_index(servers, name)
    if idx is None:
        raise KeyError(f"servidor não encontrado: {name}")
    servers[idx]["enabled"] = enabled


def set_tool_override(
    data: CommentedMap, server_name: str, tool_name: str, risk: str | None
) -> None:
    """`risk=None` remove o override — a tool volta a seguir `trust_annotations`/
    o padrão WRITE. Edita só a chave `tool_overrides` do servidor, sem reenviar
    o resto do payload (diferente de `update_server`)."""
    servers: CommentedSeq = data["servers"]
    idx = _find_index(servers, server_name)
    if idx is None:
        raise KeyError(f"servidor não encontrado: {server_name}")
    overrides = servers[idx].get("tool_overrides") or CommentedMap()
    if risk is None:
        overrides.pop(tool_name, None)
    else:
        overrides[tool_name] = risk
    servers[idx]["tool_overrides"] = overrides
