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

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sicoobito.config import get_settings
from sicoobito.db.base import Base

# Lido na importação porque a dimensão faz parte do DDL: alterá-la em runtime
# não faria sentido sem migrar a tabela.
EMBEDDING_DIM = get_settings().embedding_dim


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
    # Tokens economizados por técnica. Sem este detalhamento, `tokens_saved`
    # diz que houve economia mas não qual engine a produziu — e aí não há como
    # decidir qual delas vale o custo de manter.
    savings_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    complexity: Mapped[str | None] = mapped_column(String(16), nullable=True)

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


class IndexedFile(Base):
    """Um arquivo do workspace presente no índice.

    `content_hash` é o que torna a reindexação incremental: arquivo com hash
    inalterado é pulado inteiro, sem parse e sem embedding.
    """

    __tablename__ = "indexed_file"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mtime: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # True quando o corte foi por linha em vez de por símbolo — útil para saber
    # onde a qualidade do índice é menor.
    fallback_chunking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list[CodeChunk]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("uq_indexed_file_workspace_path", "workspace", "path", unique=True),
    )


class CodeChunk(Base):
    """Um trecho indexável: idealmente uma função, classe ou método inteiro.

    `path` e `symbol` são desnormalizados de propósito — a busca devolve
    resultados sem precisar de join, e o custo de duas colunas repetidas é
    irrelevante perto disso.
    """

    __tablename__ = "code_chunk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indexed_file.id", ondelete="CASCADE"), nullable=False
    )
    workspace: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)

    symbol: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="block", nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # Coluna gerada pelo Postgres (ver migração 0002): não precisa manutenção e
    # nunca fica dessincronizada do `content`. Config `simple` porque stemming
    # de inglês estraga identificador de código.
    #
    # `Computed` não é decoração: sem ele o SQLAlchemy inclui `tsv` no INSERT, e
    # o Postgres recusa qualquer escrita numa coluna GENERATED ALWAYS.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
        nullable=True,
    )

    file: Mapped[IndexedFile] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_code_chunk_workspace_path", "workspace", "path"),
        Index("ix_code_chunk_symbol", "workspace", "symbol"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<CodeChunk {self.path}:{self.start_line}-{self.end_line} {self.symbol or ''}>"


class Document(Base):
    """Um documento (PDF) enviado para o RAG. O blob mora no MinIO; aqui só
    ficam metadados e o estado da ingestão."""

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    minio_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    minio_object: Mapped[str] = mapped_column(String(512), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # pending -> processing -> ready | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_document_status", "status"),)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<Document {self.filename} {self.status}>"


class DocumentChunk(Base):
    """Um trecho embeddável de um documento — igual em espírito a `CodeChunk`,
    mas orientado a página/parágrafo em vez de símbolo de código."""

    __tablename__ = "document_chunk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
        nullable=True,
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (Index("ix_document_chunk_document_id", "document_id"),)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<DocumentChunk {self.document_id} #{self.chunk_index}>"


class Note(Base):
    """Uma nota do Segundo Cérebro. `links` é resolvido no servidor a cada
    save, a partir de `[[wikilinks]]` no conteúdo — não confiado ao cliente,
    para o agente também poder criar/atualizar notas de forma consistente."""

    __tablename__ = "note"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    links: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list[NoteChunk]] = relationship(
        back_populates="note", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<Note {self.title!r}>"


class NoteChunk(Base):
    """Um trecho embeddável de uma nota — mesmo espírito de `DocumentChunk`."""

    __tablename__ = "note_chunk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("note.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
        nullable=True,
    )

    note: Mapped[Note] = relationship(back_populates="chunks")

    __table_args__ = (Index("ix_note_chunk_note_id", "note_id"),)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<NoteChunk {self.note_id} #{self.chunk_index}>"


class Skill(Base):
    """Preset de prompt de sistema reusável — pelo usuário na UI ou pelo
    próprio agente via `list_skills`/`get_skill`."""

    __tablename__ = "skill"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="automation", nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Texto JSON cru, editado pelo usuário como JSON Schema livre — não é
    # validado/parseado no backend, mesma semântica que a UI já tinha.
    parameters_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_skill_enabled", "enabled"),)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<Skill {self.name!r} enabled={self.enabled}>"


class AuditLogEntry(Base):
    """Uma linha de auditoria. `event_metadata` (não `metadata` — reservado
    pelo `Base` do SQLAlchemy) carrega o que não cabe nos campos fixos."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_module", "module"),
        Index("ix_audit_log_risk_level", "risk_level"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<AuditLogEntry {self.module} {self.action!r} {self.status}>"


class AgentSessionRecord(Base):
    """Metadados de uma sessão do agente, para o histórico sobreviver a um restart.

    `session_id` é a chave primária, não um UUID sintético: já é o identificador
    natural usado em todo o resto do sistema (dict em memória do `AgentRunner`,
    rotas `/api/agent/sessions/{id}`), gerado por `SandboxManager.new_session_id()`
    como 12 chars hex. Duplicar em UUID só criaria uma tradução sem ganho.

    O grafo em si (mensagens, estado do LangGraph) não mora aqui — isso já é
    responsabilidade do checkpointer do Postgres. Esta tabela guarda só o que uma
    lista de histórico precisa mostrar e filtrar sem reconstruir o grafo inteiro.
    """

    __tablename__ = "agent_session"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project: Mapped[str] = mapped_column(String(255), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "open" | "closed" — só muda em close_session(); uma aba fechada sem
    # encerrar a sessão explicitamente fica "open" pra sempre aqui. Quem
    # consome esta tabela precisa combinar com o dict em memória do runner
    # (campo `live` na view da API) para saber o que está realmente ativo.
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_session_project_updated", "project", "updated_at"),
        Index("ix_agent_session_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<AgentSessionRecord {self.session_id} {self.status} {self.task[:40]!r}>"
