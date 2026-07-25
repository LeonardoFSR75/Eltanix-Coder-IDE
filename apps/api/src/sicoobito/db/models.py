"""Modelos persistidos.

Deliberadamente **não** existem tabelas `provider` e `model`: a configuração de
modelos e rotas vive em `config/*.yaml` e é a única fonte de verdade. Duplicá-la
no banco criaria um problema de sincronização sem nenhum ganho — o banco aqui
guarda telemetria, não configuração.

Também não existe `usage_daily`: os agregados são derivados de `request_log` por
consulta. Para um uso local-first o volume é pequeno, e agregado derivado nunca
fica defasado do fato.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sicoobito.db.base import Base


class RequestLog(Base):
    """Uma linha por chamada de LLM que saiu da plataforma.

    Como o router é a única porta de saída (ver ADR 0001), nenhuma chamada
    escapa deste registro — é o que torna a contabilidade de custo confiável.
    """

    __tablename__ = "request_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Origem ──────────────────────────────────────────────────────────────
    # `source` identifica quem chamou (cline, continue, aider, ide, agent...),
    # para saber qual ferramenta está gastando.
    source: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), default="chat", nullable=False)

    # ── Roteamento ──────────────────────────────────────────────────────────
    requested_model: Mapped[str] = mapped_column(String(128), nullable=False)
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Candidatos tentados antes do que respondeu; lista vazia = acertou de primeira.
    fallback_from: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # ── Resultado ───────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stream: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Tokens ──────────────────────────────────────────────────────────────
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Contagem estimada localmente porque o provedor não devolveu `usage`.
    usage_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Custo ───────────────────────────────────────────────────────────────
    cost_usd: Mapped[float] = mapped_column(Numeric(14, 8), default=0, nullable=False)
    # False quando o modelo não está em pricing.yaml: custo 0 aqui significa
    # "desconhecido", não "de graça".
    cost_known: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Economia ────────────────────────────────────────────────────────────
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tokens_saved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_saved_usd: Mapped[float] = mapped_column(Numeric(14, 8), default=0, nullable=False)

    __table_args__ = (
        Index("ix_request_log_created_at", "created_at"),
        Index("ix_request_log_model_created", "resolved_model", "created_at"),
        Index("ix_request_log_source_created", "source", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return (
            f"<RequestLog {self.resolved_model} {self.status} "
            f"{self.total_tokens}tok ${self.cost_usd}>"
        )
