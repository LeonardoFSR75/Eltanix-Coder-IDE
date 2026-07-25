"""Seleção e ordenação de candidatos por perfil de roteamento.

A política decide *a ordem de tentativa*; quem executa a tentativa e o fallback
é o `RouterEngine`. Manter a decisão separada da execução permite testar a
ordenação sem chamar nenhum modelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sicoobito.logging_setup import get_logger
from sicoobito.router.catalog import Catalog, ModelSpec, RouteProfile
from sicoobito.router.health import HealthTracker
from sicoobito.router.pricing import PriceTable, Usage

log = get_logger(__name__)

# Razão output/input assumida ao estimar o custo antes de gerar a resposta.
_ASSUMED_OUTPUT_RATIO = 0.35
# Margem sobre a janela de contexto reservada para a resposta.
_CONTEXT_HEADROOM = 0.85


@dataclass(slots=True)
class Candidate:
    spec: ModelSpec
    score: float = 0.0
    estimated_cost_usd: Decimal = Decimal(0)
    latency_p95_ms: int | None = None
    healthy: bool = True
    excluded_reason: str | None = None


@dataclass(slots=True)
class RoutingDecision:
    profile: str | None
    strategy: str
    candidates: list[Candidate]
    excluded: list[Candidate]

    @property
    def order(self) -> list[str]:
        return [c.spec.id for c in self.candidates]


class RoutingPolicy:
    def __init__(self, catalog: Catalog, prices: PriceTable, health: HealthTracker) -> None:
        self.catalog = catalog
        self.prices = prices
        self.health = health

    def resolve_target(self, requested_model: str) -> tuple[RouteProfile | None, ModelSpec | None]:
        """Interpreta o campo `model` do cliente.

        Aceita três formas: um perfil (`auto`), um perfil prefixado (`auto/cheap`,
        para clientes que exigem barra) ou um id concreto do catálogo.
        """
        if spec := self.catalog.get(requested_model):
            return None, spec

        name = requested_model
        if name.startswith("auto/"):
            name = name.split("/", 1)[1]
        if profile := self.catalog.profile(name):
            return profile, None
        return None, None

    async def _build_candidate(
        self, spec: ModelSpec, estimated_prompt_tokens: int
    ) -> Candidate:
        candidate = Candidate(spec=spec)

        if not spec.enabled:
            candidate.excluded_reason = "desabilitado no providers.yaml"
            return candidate
        if not spec.available:
            candidate.excluded_reason = spec.unavailable_reason or "credenciais ausentes"
            return candidate

        # Não adianta tentar um modelo cuja janela não comporta o prompt: o erro
        # viria depois de pagar a latência.
        if estimated_prompt_tokens > spec.context_window * _CONTEXT_HEADROOM:
            candidate.excluded_reason = (
                f"contexto não cabe ({estimated_prompt_tokens} tok > "
                f"{spec.context_window} de janela)"
            )
            return candidate

        candidate.healthy = await self.health.is_available(spec.id)
        if not candidate.healthy:
            candidate.excluded_reason = "circuito aberto (cooldown)"
            return candidate

        estimated_output = int(estimated_prompt_tokens * _ASSUMED_OUTPUT_RATIO)
        candidate.estimated_cost_usd = self.prices.cost(
            spec.id,
            Usage(prompt_tokens=estimated_prompt_tokens, completion_tokens=estimated_output),
        ).usd
        candidate.latency_p95_ms = await self.health.latency_p95(spec.id)
        return candidate

    async def select(
        self,
        *,
        requested_model: str,
        estimated_prompt_tokens: int,
        require_embedding: bool = False,
    ) -> RoutingDecision:
        profile, direct = self.resolve_target(requested_model)

        if direct is not None:
            # Pedido explícito de um modelo: respeitamos, sem fallback silencioso
            # para outro modelo — o cliente pediu aquele.
            candidate = await self._build_candidate(direct, estimated_prompt_tokens)
            ok = candidate.excluded_reason is None
            return RoutingDecision(
                profile=None,
                strategy="explicit",
                candidates=[candidate] if ok else [],
                excluded=[] if ok else [candidate],
            )

        if profile is None:
            profile = self.catalog.profile(self.catalog.default_profile)
        if profile is None:
            return RoutingDecision(profile=None, strategy="none", candidates=[], excluded=[])

        specs = [self.catalog.get(mid) for mid in profile.models]
        pool = [s for s in specs if s is not None]
        if require_embedding:
            pool = [s for s in pool if s.is_embedding]
        else:
            pool = [s for s in pool if not s.is_embedding]

        built = [await self._build_candidate(s, estimated_prompt_tokens) for s in pool]
        usable = [c for c in built if c.excluded_reason is None]
        excluded = [c for c in built if c.excluded_reason is not None]

        ordered = self._order(usable, profile)
        return RoutingDecision(
            profile=profile.name,
            strategy=profile.strategy,
            candidates=ordered,
            excluded=excluded,
        )

    def _order(self, candidates: list[Candidate], profile: RouteProfile) -> list[Candidate]:
        if not candidates:
            return []

        strategy = profile.strategy
        if strategy == "priority":
            rank = {mid: i for i, mid in enumerate(profile.models)}
            return sorted(candidates, key=lambda c: rank.get(c.spec.id, len(rank)))

        if strategy == "cost":
            return sorted(candidates, key=lambda c: (c.estimated_cost_usd, c.spec.id))

        if strategy == "latency":
            # Sem amostra de latência ainda, o modelo vai para o fim em vez de
            # ser presumido rápido — evita eleger um provedor nunca testado.
            return sorted(
                candidates,
                key=lambda c: (c.latency_p95_ms if c.latency_p95_ms is not None else 10**9),
            )

        if strategy == "score":
            return self._order_by_score(candidates, profile)

        log.warning("policy.unknown_strategy", strategy=strategy, profile=profile.name)
        return candidates

    def _order_by_score(
        self, candidates: list[Candidate], profile: RouteProfile
    ) -> list[Candidate]:
        weights = profile.weights or {
            "health": 0.3,
            "cost": 0.25,
            "latency": 0.2,
            "success_rate": 0.15,
            "context_fit": 0.1,
        }

        costs = [float(c.estimated_cost_usd) for c in candidates]
        latencies = [
            float(c.latency_p95_ms) for c in candidates if c.latency_p95_ms is not None
        ]
        max_cost = max(costs) if costs else 0.0
        max_latency = max(latencies) if latencies else 0.0
        max_window = max(c.spec.context_window for c in candidates)

        for candidate in candidates:
            # Cada componente é normalizado em [0,1], maior = melhor.
            cost = float(candidate.estimated_cost_usd)
            cost_score = 1.0 if max_cost == 0 else 1.0 - (cost / max_cost)

            if candidate.latency_p95_ms is None or max_latency == 0:
                # Sem histórico, assume mediano — nem premia nem pune.
                latency_score = 0.5
            else:
                latency_score = 1.0 - (float(candidate.latency_p95_ms) / max_latency)

            health_score = 1.0 if candidate.healthy else 0.0
            context_score = candidate.spec.context_window / max_window if max_window else 0.0
            # `success_rate` real exige um snapshot por modelo; a ordenação usa a
            # aproximação de saúde e o engine corrige com o breaker.
            success_score = health_score

            candidate.score = (
                weights.get("health", 0.0) * health_score
                + weights.get("cost", 0.0) * cost_score
                + weights.get("latency", 0.0) * latency_score
                + weights.get("success_rate", 0.0) * success_score
                + weights.get("context_fit", 0.0) * context_score
            )

        rank = {mid: i for i, mid in enumerate(profile.models)}
        # Empate resolvido pela ordem declarada, para o roteamento ser determinístico.
        return sorted(candidates, key=lambda c: (-c.score, rank.get(c.spec.id, len(rank))))
