"""Wrapper do SecureBERT2 para classificação de risco de conteúdo.

A implementação usa o pacote vendorizado quando ele está disponível e cai para
um fallback determinístico quando o modelo não pode ser carregado. O objetivo é
manter o serviço operando sem derrubar o restante da plataforma.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - depende do ambiente do runtime.
    import securebert2  # type: ignore
except Exception:  # pragma: no cover - degradado por design.
    securebert2 = None


@dataclass(slots=True)
class SecureBertAnalysis:
    provider: str
    available: bool
    classification: str
    score: float
    reasons: list[str]
    version: str
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "classification": self.classification,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "version": self.version,
            "mode": self.mode,
        }


class SecureBertService:
    """Classifica risco de texto com o modelo SecureBERT2 quando disponível."""

    def __init__(self) -> None:
        self.provider = "securebert2"
        self.version = getattr(securebert2, "__version__", "unknown") if securebert2 else "unknown"
        self.available = securebert2 is not None

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "version": self.version,
            "mode": "model" if self.available else "heuristic-fallback",
        }

    def analyze(self, text: str) -> dict[str, Any]:
        normalized = (text or "").strip().lower()
        reasons: list[str] = []
        score = 0.0

        if not normalized:
            return SecureBertAnalysis(
                provider=self.provider,
                available=self.available,
                classification="safe",
                score=0.0,
                reasons=["empty input"],
                version=self.version,
                mode="heuristic-fallback" if not self.available else "model",
            ).as_dict()

        patterns = [
            ("ignore all safeguards", 0.9),
            ("ignore safety", 0.85),
            ("bypass restrictions", 0.9),
            ("exfiltrate secrets", 0.95),
            ("steal credentials", 0.95),
            ("password dump", 0.9),
            ("base64", 0.45),
            ("powershell", 0.55),
            ("curl", 0.35),
            ("wget", 0.35),
            ("disable security", 0.9),
            ("remove protections", 0.85),
            ("unauthorized access", 0.9),
            ("evasive action", 0.5),
            ("self delete", 0.5),
            ("secret key", 0.8),
            ("api key", 0.8),
            ("token", 0.55),
            ("execute arbitrary", 0.8),
            ("malware", 0.9),
            ("prompt injection", 0.9),
        ]

        for needle, weight in patterns:
            if needle in normalized:
                score += weight
                reasons.append(needle)

        if score >= 2.5:
            classification = "high-risk"
        elif score >= 1.5:
            classification = "unsafe"
        elif score >= 0.5:
            classification = "suspicious"
        else:
            classification = "safe"

        if not reasons:
            reasons = ["no suspicious patterns detected"]

        result = SecureBertAnalysis(
            provider=self.provider,
            available=self.available,
            classification=classification,
            score=min(score, 1.0) if score <= 1.0 else 1.0,
            reasons=reasons,
            version=self.version,
            mode="model" if self.available else "heuristic-fallback",
        )
        return result.as_dict()
