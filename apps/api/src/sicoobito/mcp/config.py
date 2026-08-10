"""Config declarativa de servidores MCP: leitura de `config/mcp.yaml`.

Mesmo padrão de `router/catalog.py`: leitura simples via `yaml.safe_load` (a
escrita, que precisa preservar comentários, fica em `mcp/config_editor.py`
via `ruamel.yaml` — mesma separação que `catalog.py`/`providers_editor.py`
já usam).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    """Substitui ${VAR} pelo valor do ambiente — mesma convenção de
    `providers.yaml`, para segredos (tokens de servidores MCP remotos) não
    precisarem ficar em texto puro no arquivo."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class MCPServerConfig(BaseModel):
    name: str
    transport: Literal["stdio", "http"]
    enabled: bool = True
    # Anotações (`read_only_hint` etc.) são um sinal do servidor, não uma
    # garantia — a especificação do MCP recomenda não confiar nelas às cegas.
    # Só um servidor marcado aqui explicitamente tem suas tools rebaixadas de
    # WRITE para READ quando anunciam `read_only_hint: true`.
    trust_annotations: bool = False
    # Override manual por ferramenta (nome remoto, não o `mcp__servidor__tool`
    # composto) — tem precedência sobre `trust_annotations`. Permite confiar
    # (ou desconfiar) de UMA tool específica sem promover/rebaixar as outras
    # do mesmo servidor.
    tool_overrides: dict[str, Literal["read", "write"]] = Field(default_factory=dict)

    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # http (Streamable HTTP)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valida_campos_por_transporte(self) -> MCPServerConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"servidor {self.name!r}: transporte stdio exige 'command'")
        if self.transport == "http" and not self.url:
            raise ValueError(f"servidor {self.name!r}: transporte http exige 'url'")
        return self


def load_mcp_servers(path: Path) -> list[MCPServerConfig]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    entries = raw.get("servers") or []
    return [MCPServerConfig(**_expand_env(entry)) for entry in entries]


class MCPCatalogTemplate(BaseModel):
    """Um servidor MCP conhecido, oferecido como atalho de cadastro na UI.

    Estático — nunca guarda valor sensível, só os *nomes* de variável/
    placeholder que a UI precisa pedir ao usuário (`required_env`,
    `required_args` casando com `{chave}` dentro de `args`)."""

    id: str
    label: str
    description: str = ""
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    required_env: list[str] = Field(default_factory=list)
    required_args: list[str] = Field(default_factory=list)
    note: str = ""


def load_catalog(path: Path) -> list[MCPCatalogTemplate]:
    """Não passa por `_expand_env`: é catálogo de referência, não config com
    segredo — os valores reais só entram quando o usuário cadastra o servidor
    de verdade em `mcp.yaml`."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    entries = raw.get("templates") or []
    return [MCPCatalogTemplate(**entry) for entry in entries]
