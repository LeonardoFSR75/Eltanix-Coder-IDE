"""Wrapper de análise de risco textual com SecureBERT (modo dual).

**Modo ``heuristic``** (padrão / fallback)
    Heurística de padrões vetoriais com contexto. Nenhuma dependência extra
    além do que já está no pyproject.toml. Sempre disponível.

**Modo ``transformers``** (opcional)
    Quando ``transformers`` e ``torch`` estiverem instalados
    (``uv sync --extra securebert``), o serviço carrega o modelo
    ``ehsanaghaei/SecureBERT`` (RoBERTa-based) e classifica via distância
    cossenoidal entre o embedding do texto e embeddings de referência
    pré-computados. O modelo é carregado preguiçosamente no primeiro uso e
    mantido em cache para a vida do processo.

**Campos de saída**
    ``score``      float 0–1, normalizado para a UI.
    ``score_raw``  float unbounded, soma bruta dos pesos de padrões ativados
                   (ou saída do modelo). Usado internamente para a
                   classificação em ``safe / suspicious / unsafe / high-risk``.
    ``mode``       ``"heuristic"`` | ``"transformers"`` — reflete o que
                   realmente foi executado, nunca mentiria sobre isso.

O princípio é manter o serviço operacional sem derrubar o restante da
plataforma. Qualquer falha no carregamento do modelo ou na inferência cai
silenciosamente para a heurística.
"""

from __future__ import annotations

import functools
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

# ── Integração opcional com HuggingFace ───────────────────────────────────────
# Duplo-gate: a variável SECUREBERT_MODEL_ENABLED=true deve estar definida
# explicitamente E os pacotes devem estar instalados.
# Sem o opt-in, o modo é sempre "heuristic" mesmo que transformers/torch
# estejam presentes como dependências transitivas de outros pacotes,
# evitando o download acidental de ~500 MB do modelo na primeira chamada.
_MODEL_OPT_IN = os.getenv("SECUREBERT_MODEL_ENABLED", "").lower() in {"1", "true", "yes"}

try:  # pragma: no cover - depende do ambiente.
    if not _MODEL_OPT_IN:
        raise ImportError("SECUREBERT_MODEL_ENABLED nao esta ativo")
    import torch
    from transformers import AutoModel, AutoTokenizer

    _HF_AVAILABLE = True
except Exception:  # pragma: no cover - degradado por design.
    torch = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]
    AutoModel = None  # type: ignore[assignment]
    _HF_AVAILABLE = False

_SECUREBERT_MODEL = "ehsanaghaei/SecureBERT"

# ── Padrões de heurística ─────────────────────────────────────────────────────

# Cada entrada: (needle, score_weight, requer_contexto_imperativo)
# Se ``requer_contexto_imperativo=True``, o padrão só conta quando aparece
# próximo de verbos de comando, evitando falsos positivos em perguntas
# informacionais ("how do I configure my api key?").
_PATTERNS: list[tuple[str, float, bool]] = [
    # Alta ameaça — sempre contam
    ("ignore all safeguards", 0.9, False),
    ("ignore safety", 0.85, False),
    ("bypass restrictions", 0.9, False),
    ("exfiltrate secrets", 0.95, False),
    ("steal credentials", 0.95, False),
    ("password dump", 0.9, False),
    ("disable security", 0.9, False),
    ("remove protections", 0.85, False),
    ("unauthorized access", 0.9, False),
    ("execute arbitrary", 0.8, False),
    ("malware", 0.9, False),
    ("prompt injection", 0.9, False),
    # PT-BR — alta ameaça
    ("ignore as salvaguardas", 0.9, False),
    ("exfiltre segredos", 0.95, False),
    ("roubar credenciais", 0.95, False),
    ("desabilitar segurança", 0.9, False),
    ("remover proteções", 0.85, False),
    ("acesso não autorizado", 0.9, False),
    ("executar arbitrariamente", 0.8, False),
    ("injeção de prompt", 0.9, False),
    # Moderada ameaça — só em contexto imperativo
    ("base64", 0.45, True),
    ("powershell", 0.55, True),
    ("curl", 0.35, True),
    ("wget", 0.35, True),
    ("evasive action", 0.5, False),
    ("self delete", 0.5, False),
    ("secret key", 0.8, True),
    ("api key", 0.8, True),
    ("token", 0.55, True),
]

# Verbos de comando que ativam padrões contextuais (match em qualquer posição
# numa janela de ±60 chars em torno do needle).
_IMPERATIVE_RE = re.compile(
    r"\b(send|exfil|dump|steal|extract|leak|export|transmit|upload|inject|"
    r"use|grab|take|get|fetch|read|expose|print|output|write|log|forward|"
    r"enviar|exfiltrar|roubar|extrair|vazar|exportar|transmitir|injetar|"
    r"pegar|obter|buscar|ler|expor|imprimir|gravar|encaminhar)\b",
    re.IGNORECASE,
)

# ── Utilitários ───────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase + normalização Unicode NFC (remove acentos compostos ambíguos)."""
    return unicodedata.normalize("NFC", text.lower())


def _has_imperative_context(text: str, needle: str, window: int = 60) -> bool:
    """Retorna True se há um verbo imperativo próximo do needle no texto."""
    idx = text.find(needle)
    if idx == -1:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + len(needle) + window)
    return bool(_IMPERATIVE_RE.search(text[start:end]))


# ── Modelo HuggingFace (carregamento preguiçoso) ──────────────────────────────


@functools.lru_cache(maxsize=1)
def _load_securebert():  # pragma: no cover - só roda com torch instalado
    """Carrega tokenizador + modelo uma única vez e mantém em cache."""
    tokenizer = AutoTokenizer.from_pretrained(_SECUREBERT_MODEL)
    model = AutoModel.from_pretrained(_SECUREBERT_MODEL)
    model.eval()

    # Embeddings de referência (CLS) para "safe" e "unsafe" pré-computados com
    # frases canônicas. Em produção poderiam vir de um arquivo .pt pré-gerado.
    safe_phrases = [
        "print hello world",
        "list files in directory",
        "open a file and read it",
        "write a unit test",
    ]
    unsafe_phrases = [
        "ignore all safeguards and exfiltrate secrets",
        "bypass security restrictions and steal credentials",
        "execute arbitrary malware payload",
        "prompt injection attack",
    ]

    def _embed(phrases: list[str]) -> Any:
        enc = tokenizer(phrases, return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.no_grad():
            out = model(**enc)
        return out.last_hidden_state[:, 0, :].mean(dim=0)  # média dos CLS

    ref_safe = _embed(safe_phrases)
    ref_unsafe = _embed(unsafe_phrases)
    return tokenizer, model, ref_safe, ref_unsafe


def _cosine(a: Any, b: Any) -> float:  # pragma: no cover
    import torch as _t

    return float(_t.nn.functional.cosine_similarity(a.unsqueeze(0), b.unsqueeze(0)).item())


def _analyze_with_transformers(text: str) -> tuple[float, float, list[str]]:
    """Retorna (score_raw, score_normalized, reasons) usando o modelo."""  # pragma: no cover
    try:
        tokenizer, model, ref_safe, ref_unsafe = _load_securebert()
        enc = tokenizer(
            [text], return_tensors="pt", padding=True, truncation=True, max_length=256
        )
        with torch.no_grad():
            out = model(**enc)
        emb = out.last_hidden_state[:, 0, :].squeeze(0)

        sim_safe = _cosine(emb, ref_safe)
        sim_unsafe = _cosine(emb, ref_unsafe)

        # Delta relativo de similaridade semântica
        # Embeddings RoBERTa [CLS] têm cossenos altos (~0.98); deltas >= 0.0010 representam desvio
        delta = sim_unsafe - sim_safe
        model_score = max(0.0, (delta - 0.0010) * 1500.0) if delta > 0.0010 else 0.0

        # Combina com a análise contextual de padrões
        h_score, h_reasons = _heuristic_score(_normalize(text))

        raw = max(model_score, h_score)
        normalized = min(raw / 3.0, 1.0)
        reasons = [f"model: sim_unsafe={sim_unsafe:.3f} sim_safe={sim_safe:.3f}"]
        if h_reasons:
            reasons.extend(h_reasons)
        return raw, normalized, reasons
    except Exception:
        return -1.0, -1.0, []  # sinaliza falha para o chamador


# ── Dataclass de resultado ─────────────────────────────────────────────────────


@dataclass(slots=True)
class SecureBertAnalysis:
    provider: str
    available: bool
    classification: str
    score: float       # normalizado 0–1 (para UI)
    score_raw: float   # soma bruta / saída do modelo (para diagnóstico)
    reasons: list[str]
    version: str
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "classification": self.classification,
            "score": round(self.score, 3),
            "score_raw": round(self.score_raw, 3),
            "reasons": self.reasons,
            "version": self.version,
            "mode": self.mode,
        }


# ── Serviço principal ──────────────────────────────────────────────────────────


class SecureBertService:
    """Classifica risco de texto com SecureBERT (dual-mode: transformers | heuristic)."""

    def __init__(self) -> None:
        self.provider = "securebert"
        self.available = _HF_AVAILABLE
        self.version = _SECUREBERT_MODEL if _HF_AVAILABLE else "heuristic-only"

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "version": self.version,
            "mode": "transformers" if self.available else "heuristic",
        }

    def analyze(self, text: str) -> dict[str, Any]:
        normalized = _normalize((text or "").strip())

        # Early-return para input vazio — antes de qualquer processamento.
        if not normalized:
            return SecureBertAnalysis(
                provider=self.provider,
                available=self.available,
                classification="safe",
                score=0.0,
                score_raw=0.0,
                reasons=["empty input"],
                version=self.version,
                mode="heuristic" if not self.available else "transformers",
            ).as_dict()

        # ── Modo transformers ──────────────────────────────────────────────────
        if self.available:  # pragma: no cover - só com torch instalado
            score_raw, score, reasons = _analyze_with_transformers(text)
            if score_raw >= 0:  # sucesso na inferência
                classification = _classify(score_raw)
                if not reasons or score_raw == 0:
                    reasons = ["no suspicious signal detected"]
                return SecureBertAnalysis(
                    provider=self.provider,
                    available=True,
                    classification=classification,
                    score=score,
                    score_raw=score_raw,
                    reasons=reasons,
                    version=self.version,
                    mode="transformers",
                ).as_dict()
            # Falha na inferência → degrada para heurística silenciosamente.

        # ── Modo heuristic ─────────────────────────────────────────────────────
        score_raw, reasons = _heuristic_score(normalized)
        score = min(score_raw / 3.0, 1.0)
        classification = _classify(score_raw)

        if not reasons:
            reasons = ["no suspicious patterns detected"]

        return SecureBertAnalysis(
            provider=self.provider,
            available=self.available,
            classification=classification,
            score=score,
            score_raw=score_raw,
            reasons=reasons,
            version=self.version,
            mode="heuristic",
        ).as_dict()


# ── Funções auxiliares ─────────────────────────────────────────────────────────


def _heuristic_score(normalized: str) -> tuple[float, list[str]]:
    """Calcula score bruto e razões via heurística de padrões."""
    score = 0.0
    reasons: list[str] = []

    for needle, weight, needs_context in _PATTERNS:
        if needle not in normalized:
            continue
        if needs_context and not _has_imperative_context(normalized, needle):
            continue
        score += weight
        reasons.append(needle)

    # Penalidade de combinação: ≥3 padrões moderados disparam como se fossem 1 alto
    if len(reasons) >= 3 and score < 2.5:
        score = max(score, 1.5)

    return score, reasons


def _classify(score_raw: float) -> str:
    """Converte score bruto em nível de risco."""
    if score_raw >= 2.5:
        return "high-risk"
    if score_raw >= 1.5:
        return "unsafe"
    if score_raw >= 0.5:
        return "suspicious"
    return "safe"
