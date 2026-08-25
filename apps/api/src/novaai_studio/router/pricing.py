"""Tabela de preços e cálculo de custo.

Regra que atravessa o módulo: custo desconhecido nunca vira zero. Um modelo
ausente de `pricing.yaml` produz `cost_known=False`, e o dashboard mostra isso
como lacuna em vez de contabilizar uma economia que não existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

_MILLION = Decimal(1_000_000)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @classmethod
    def from_litellm(cls, usage: object) -> Usage:
        """Normaliza o `usage` do litellm, que varia bastante entre provedores."""
        if usage is None:
            return cls()

        def _get(obj: object, *names: str) -> int:
            for name in names:
                value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        continue
            return 0

        prompt = _get(usage, "prompt_tokens", "input_tokens")
        completion = _get(usage, "completion_tokens", "output_tokens")

        # Detalhes de cache vêm em subobjetos com nomes diferentes por provedor.
        details = (
            usage.get("prompt_tokens_details")
            if isinstance(usage, dict)
            else getattr(usage, "prompt_tokens_details", None)
        )
        cache_read = _get(details, "cached_tokens") if details is not None else 0
        if not cache_read:
            cache_read = _get(usage, "cache_read_input_tokens")
        cache_write = _get(usage, "cache_creation_input_tokens")

        # Nos provedores que reportam cache separado, `prompt_tokens` já inclui os
        # tokens lidos do cache; separá-los evita cobrar duas vezes o mesmo token.
        prompt = max(prompt - cache_read, 0) if cache_read and prompt >= cache_read else prompt

        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )


@dataclass(slots=True)
class Price:
    input: Decimal | None
    output: Decimal | None
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None

    @property
    def known(self) -> bool:
        return self.input is not None and self.output is not None


@dataclass(slots=True)
class CostResult:
    usd: Decimal
    known: bool


class PriceTable:
    def __init__(self, prices: dict[str, Price], updated_at: str | None = None) -> None:
        self._prices = prices
        self.updated_at = updated_at

    @classmethod
    def load(cls, path: Path) -> PriceTable:
        if not path.exists():
            log.warning("pricing.file.missing", path=str(path))
            return cls({})
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        def _dec(value: object) -> Decimal | None:
            if value is None:
                return None
            return Decimal(str(value))

        prices = {
            model_id: Price(
                input=_dec(cfg.get("input")),
                output=_dec(cfg.get("output")),
                cache_read=_dec(cfg.get("cache_read")),
                cache_write=_dec(cfg.get("cache_write")),
            )
            for model_id, cfg in (raw.get("models") or {}).items()
        }
        log.info("pricing.loaded", models=len(prices), updated_at=raw.get("updated_at"))
        return cls(prices, updated_at=raw.get("updated_at"))

    def price_of(self, model_id: str) -> Price | None:
        return self._prices.get(model_id)

    def cost(self, model_id: str, usage: Usage) -> CostResult:
        price = self._prices.get(model_id)
        if price is None or not price.known:
            return CostResult(usd=Decimal(0), known=False)

        assert price.input is not None and price.output is not None
        total = (
            Decimal(usage.prompt_tokens) * price.input
            + Decimal(usage.completion_tokens) * price.output
        )
        # Sem preço de cache declarado, tokens de cache custam como input normal.
        total += Decimal(usage.cache_read_tokens) * (
            price.cache_read if price.cache_read is not None else price.input
        )
        total += Decimal(usage.cache_write_tokens) * (
            price.cache_write if price.cache_write is not None else price.input
        )
        return CostResult(usd=total / _MILLION, known=True)
