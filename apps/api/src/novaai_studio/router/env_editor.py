"""Leitura e escrita pontual de pares `CHAVE=valor` no `.env` da raiz.

Diferente do `routes_editor` (YAML estrutural, precisa de round-trip), o
`.env` já é linha-a-chave: basta achar `^CHAVE=` e trocar o valor, ou
acrescentar a linha no fim se a chave ainda não existir. Comentários e todo o
resto do arquivo ficam como estão — nunca é um `yaml.safe_dump`-like
reescrevendo o arquivo inteiro.
"""

from __future__ import annotations

import re
from pathlib import Path


def _key_pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)


def read_values(env_file: Path, keys: list[str]) -> dict[str, str]:
    """Valor atual de cada chave. Arquivo ausente conta como tudo vazio."""
    if not env_file.exists():
        return dict.fromkeys(keys, "")
    text = env_file.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for key in keys:
        match = _key_pattern(key).search(text)
        found[key] = match.group(0).split("=", 1)[1] if match else ""
    return found


def write_values(env_file: Path, values: dict[str, str]) -> None:
    """Atualiza ou acrescenta `CHAVE=valor` para cada entrada de `values`.

    Uma chave que já existe tem sua linha substituída no lugar; uma chave nova
    vai para o fim do arquivo. Nada mais no arquivo é tocado.
    """
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    for key, value in values.items():
        if "\n" in key or "\r" in key or "\n" in value or "\r" in value:
            raise ValueError(f"chave ou valor de env não pode conter quebra de linha: {key!r}")
        pattern = _key_pattern(key)
        linha = f"{key}={value}"
        if pattern.search(text):
            text = pattern.sub(linha, text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{linha}\n"
    env_file.write_text(text, encoding="utf-8")
