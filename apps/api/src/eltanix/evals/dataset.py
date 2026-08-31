"""Casos de avaliação de qualidade do RAG: carrega `config/eval_dataset.yaml`.

Dois modos de acerto por caso, porque curar IDs exatos de chunk é trabalhoso:
`expected_keywords` (substring no conteúdo devolvido — mais fácil de escrever
à mão) ou `expected_ids` (id exato do hit — mais preciso quando disponível).

O bloco `defaults` no topo do YAML evita repetir `root` em cada caso: com
dezenas de casos apontando para o mesmo workspace, repetir o caminho absoluto
significa que ninguém consegue rodar o dataset de outra máquina sem editar o
arquivo inteiro. `root` também expande `${VAR}` do ambiente, então o caminho
padrão é `${ELTANIX_EVAL_ROOT}` e cada máquina só define a variável.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

EvalSource = Literal["documents", "notes", "context"]

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: str) -> str:
    return _ENV_RE.sub(lambda m: os.getenv(m.group(1), ""), value)


class EvalCase(BaseModel):
    source: EvalSource
    query: str
    expected_keywords: list[str] = Field(default_factory=list)
    expected_ids: list[str] = Field(default_factory=list)
    # Só usado quando source == "context": raiz do workspace já indexado.
    root: str | None = None
    limit: int = 8
    # Rótulo livre para fatiar o relatório (ex.: "router", "agente", "rag").
    # Uma média única esconde que a recuperação quebrou só numa área.
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valida(self) -> EvalCase:
        if not self.expected_keywords and not self.expected_ids:
            raise ValueError(f"caso {self.query!r}: informe expected_keywords ou expected_ids")
        if self.source == "context" and not self.root:
            raise ValueError(
                f"caso {self.query!r}: source=context exige 'root' (no caso ou em `defaults`). "
                "Se o dataset usa ${ELTANIX_EVAL_ROOT}, defina a variável de ambiente."
            )
        return self


def load_dataset(path: Path) -> list[EvalCase]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    defaults: dict[str, Any] = dict(raw.get("defaults") or {})
    casos: list[EvalCase] = []
    for entry in raw.get("cases") or []:
        merged: dict[str, Any] = {**defaults, **dict(entry)}
        if isinstance(merged.get("root"), str):
            expandido = _expand_env(merged["root"]).strip()
            merged["root"] = expandido or None
        casos.append(EvalCase(**merged))
    return casos
