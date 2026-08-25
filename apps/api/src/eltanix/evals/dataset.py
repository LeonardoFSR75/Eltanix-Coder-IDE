"""Casos de avaliação de qualidade do RAG: carrega `config/eval_dataset.yaml`.

Dois modos de acerto por caso, porque curar IDs exatos de chunk é trabalhoso:
`expected_keywords` (substring no conteúdo devolvido — mais fácil de escrever
à mão) ou `expected_ids` (id exato do hit — mais preciso quando disponível).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

EvalSource = Literal["documents", "notes", "context"]


class EvalCase(BaseModel):
    source: EvalSource
    query: str
    expected_keywords: list[str] = Field(default_factory=list)
    expected_ids: list[str] = Field(default_factory=list)
    # Só usado quando source == "context": raiz do workspace já indexado.
    root: str | None = None
    limit: int = 8

    @model_validator(mode="after")
    def _valida(self) -> EvalCase:
        if not self.expected_keywords and not self.expected_ids:
            raise ValueError(f"caso {self.query!r}: informe expected_keywords ou expected_ids")
        if self.source == "context" and not self.root:
            raise ValueError(f"caso {self.query!r}: source=context exige 'root'")
        return self


def load_dataset(path: Path) -> list[EvalCase]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return [EvalCase(**entry) for entry in raw.get("cases") or []]
