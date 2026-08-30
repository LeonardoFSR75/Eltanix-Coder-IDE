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
    JSON,
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

from eltanix.config import get_settings
from eltanix.db.base import Base

JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")
TSVECTOR_TYPE = TSVECTOR().with_variant(Text(), "sqlite")

# Lido na importação porque a dimensão faz parte do DDL: alterá-la em runtime
# não faria sentido sem migrar a tabela.
EMBEDDING_DIM = get_settings().embedding_dim
VECTOR_TYPE = Vector(EMBEDDING_DIM).with_variant(Text(), "sqlite")


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

    source: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), default="chat", nullable=False)
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # "api_key" para o canal de serviço (ADR 0005), ou o username de quem
    # autenticou via sessão de browser — nulo para chamadas de antes desta
    # coluna existir e para qualquer caminho que ainda não popula `identify_actor`
    # (ver `api/deps.py`). Achado na auditoria arquitetural: sem isto não havia
    # como atribuir custo de LLM a um usuário específico, só a `source`
    # (ferramenta) e `project_slug` (projeto).
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Sessão de agente que disparou esta chamada — nulo para chamadas fora do
    # fluxo do agente (ex: `/v1/chat/completions` direto) e para linhas
    # anteriores a esta coluna. Junto com `ToolSpan.session_id` e
    # `AuditLogEntry.session_id`, é a chave que permite reconstruir a linha do
    # tempo de uma sessão sem juntar as três tabelas às cegas por horário
    # (ver `telemetry/flight_recorder.py`).
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── Roteamento ──────────────────────────────────────────────────────────
    requested_model: Mapped[str] = mapped_column(String(128), nullable=False)
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Candidatos tentados antes do que respondeu; lista vazia = acertou de primeira.
    fallback_from: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
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
    savings_breakdown: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    complexity: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        Index("ix_request_log_created_at", "created_at"),
        Index("ix_request_log_model_created", "resolved_model", "created_at"),
        Index("ix_request_log_source_created", "source", "created_at"),
        Index("ix_request_log_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return (
            f"<RequestLog {self.resolved_model} {self.status} "
            f"{self.total_tokens}tok ${self.cost_usd}>"
        )


class ToolSpan(Base):
    """Uma linha por execução de ferramenta do agente ou busca de RAG.

    Espelha `RequestLog` (linha 48), mas para `telemetry/tracer.py::TraceRecorder`
    em vez de custo de LLM — o buffer em memória/Redis daquele módulo é capado e
    não sobrevive a um restart do Redis; esta tabela é o caminho durável.
    """

    __tablename__ = "tool_span"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "tool" | "rag"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | error
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_tool_span_created_at", "created_at"),
        Index("ix_tool_span_name_created", "name", "created_at"),
        Index("ix_tool_span_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<ToolSpan {self.kind}:{self.name} {self.status} {self.latency_ms}ms>"


class CachedResponseEmbedding(Base):
    """Índice semântico do cache de respostas — só aponta pra uma chave já
    existente do cache exato (`optimizer/cache.py::ResponseCache`, Redis), não
    duplica o payload: o Redis já é dono do TTL/expiração de verdade, e manter
    duas cópias criaria duas fontes de expiração que podem desincronizar."""

    __tablename__ = "cached_response_embedding"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Chave da entrada correspondente em `ResponseCache` (Redis) — nunca lida
    # sem checar se ainda existe: pode ter expirado no Redis antes desta linha.
    redis_cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR_TYPE, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_cached_response_embedding_model_expires", "model_id", "expires_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<CachedResponseEmbedding {self.model_id} {self.redis_cache_key}>"


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

    __table_args__ = (Index("uq_indexed_file_workspace_path", "workspace", "path", unique=True),)


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

    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_TYPE, nullable=True)
    # Coluna gerada pelo Postgres (ver migração 0002): não precisa manutenção e
    # nunca fica dessincronizada do `content`. Config `simple` porque stemming
    # de inglês estraga identificador de código.
    #
    # `Computed` não é decoração: sem ele o SQLAlchemy inclui `tsv` no INSERT, e
    # o Postgres recusa qualquer escrita numa coluna GENERATED ALWAYS.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR_TYPE,
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


class CodeEdge(Base):
    """Uma aresta do Code Knowledge Graph — ver `context/edges.py`.

    `kind="contains"` liga contêiner a filho (classe → método): `to_chunk_id`
    aponta para outro `code_chunk`, ambos sempre no mesmo arquivo. `kind=
    "imports"` liga arquivo a arquivo: como o alvo é o arquivo importado como
    um todo, não um símbolo específico dele, `to_chunk_id` fica nulo e
    `to_path` guarda o caminho resolvido — inventar um "chunk representante"
    do arquivo destino seria arbitrário. `workspace` é desnormalizado do
    `code_chunk` de origem pelo mesmo motivo que em `CodeChunk`: consulta sem
    join extra.
    """

    __tablename__ = "code_edge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace: Mapped[str] = mapped_column(String(512), nullable=False)
    from_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_chunk.id", ondelete="CASCADE"), nullable=False
    )
    to_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_chunk.id", ondelete="CASCADE"), nullable=True
    )
    to_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # contains | imports
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_code_edge_workspace_from", "workspace", "from_chunk_id"),
        Index("ix_code_edge_workspace_to", "workspace", "to_chunk_id"),
        Index("ix_code_edge_workspace_to_path", "workspace", "to_path"),
    )


class Document(Base):
    """Um documento (PDF) enviado para o RAG. O blob mora no MinIO; aqui só
    ficam metadados e o estado da ingestão."""

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
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
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_TYPE, nullable=True)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR_TYPE,
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
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    links: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
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
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_TYPE, nullable=True)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR_TYPE,
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
    # Vetor de embedding de `description`, usado por `skills/store.py::search_by_similarity`
    # para o roteamento automático (`SkillService.find_relevant`) — nulo até o seed/CRUD
    # conseguir calculá-lo (embedding indisponível não impede a skill de existir).
    description_embedding: Mapped[list[float] | None] = mapped_column(VECTOR_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_skill_enabled", "enabled"),)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<Skill {self.name!r} enabled={self.enabled}>"


class CustomMode(Base):
    """Modo de execução do agente definido pelo usuário (Fase 6 do upgrade do
    agente) — nome, ícone, ferramentas permitidas e bloco de prompt próprios,
    selecionável ao lado dos 7 modos embutidos (`agent/state.py::BUILTIN_MODES`).

    O `id` (texto do UUID) é o próprio valor que passa a circular como
    `mode`/`AgentSession.mode`/SSE — não existe uma segunda tabela de mapeamento.
    """

    __tablename__ = "custom_mode"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    icon: Mapped[str] = mapped_column(String(16), default="🧩", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Lista explícita de nomes de ferramenta (não classe de risco) — filtra
    # `ToolRegistry.all()` em `agent/graph.py::_tool_schemas` quando `mode` não
    # é um dos 7 literais conhecidos. Vazio == nenhuma ferramenta liberada.
    allowed_tools: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    prompt_block: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<CustomMode {self.name!r}>"


class SessionFileSnapshot(Base):
    """Conteúdo de um arquivo *antes* de uma escrita do agente (Fase 8 do
    upgrade do agente: checkpoints/rewind de sessão).

    Gravada best-effort em `agent/graph.py::act()`, sempre que uma ferramenta
    `edit_file`/`write_file` vai rodar — reaproveita a mesma leitura "antes"
    que `agent/tools/diffing.py::compute_proposed_diff` já faz para o diff de
    aprovação, então não é I/O extra, só mais um lugar que guarda o mesmo
    dado. `iteration` é `AgentState["iterations"]` no momento da escrita — o
    mesmo contador que o checkpointer do LangGraph também vê, o que permite
    `agent/snapshot_store.py::restore_targets` casar "restaurar até aqui" com
    o checkpoint correspondente sem precisar de uma segunda numeração.
    """

    __tablename__ = "session_file_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content_before: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_session_file_snapshot_session_iteration", "session_id", "iteration"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<SessionFileSnapshot {self.session_id}:{self.iteration}:{self.path!r}>"


class ExtensionState(Base):
    """Estado runtime de uma extensão (ativação, versão instalada, update
    pendente). O catálogo estático (`extensions/catalog.py::MASTER_EXTENSIONS_CATALOG`)
    continua a única fonte de metadados (nome, descrição, categoria); esta tabela
    só sobrepõe o que muda em runtime — mesmo raciocínio de `Skill`, trocando o
    arquivo `config/extensions_state.json` (sem lock, sujeito a corrupção em
    escrita concorrente) por uma linha por extensão."""

    __tablename__ = "extension_state"

    extension_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    installed_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_update_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<ExtensionState {self.extension_id!r} active={self.active}>"


class ExtensionSettings(Base):
    """Linha única (`id=1`) com as configurações globais do sistema de
    extensões — `auto_update_enabled` e o timestamp da última sincronização
    com o Open VSX Registry."""

    __tablename__ = "extension_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auto_update_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_timestamp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<ExtensionSettings auto_update={self.auto_update_enabled}>"


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
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    event_metadata: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)

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
    # String(64), não String(16): desde a Fase 6 do upgrade do agente, `mode`
    # também pode ser o id (UUID em texto, 36 chars) de um modo customizado
    # (`CustomMode`) em vez de um dos 7 literais fixos.
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Resumo compacto da sessão para a UI e para a auditoria — mantém um
    # estado de execução legível mesmo sem reconstruir o grafo inteiro.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    iterations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_approvals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_failed_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # "open" | "closed" — só muda em close_session(); uma aba fechada sem
    # encerrar a sessão explicitamente fica "open" pra sempre aqui. Quem
    # consome esta tabela precisa combinar com o dict em memória do runner
    # (campo `live` na view da API) para saber o que está realmente ativo.
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    # Sessão-pai que gerou esta via `spawn_agent` (orquestração multiagente) —
    # NULL para toda sessão raiz. Sem FK de propósito: mesma convenção do
    # resto desta tabela (`project`/`branch` também não têm FK), e um valor
    # órfão aqui é só informativo, não deve travar nada.
    parent_session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_session_project_updated", "project", "updated_at"),
        Index("ix_agent_session_status", "status"),
        Index("ix_agent_session_parent", "parent_session_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<AgentSessionRecord {self.session_id} {self.status} {self.task[:40]!r}>"


class GraphNode(Base):
    """Nó/Entidade do Grafo de Conhecimento do Segundo Cérebro (Graphify)."""

    __tablename__ = "graph_node"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace: Mapped[str] = mapped_column(String(255), default="default", nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # Note, Concept, Module, Class, ADR, etc.
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    properties: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR_TYPE, nullable=True)

    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR_TYPE,
        Computed(
            "to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(summary, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    outgoing_edges: Mapped[list[GraphEdge]] = relationship(
        "GraphEdge",
        foreign_keys="GraphEdge.source_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list[GraphEdge]] = relationship(
        "GraphEdge",
        foreign_keys="GraphEdge.target_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )
    metrics: Mapped[GraphMetrics | None] = relationship(
        "GraphMetrics", back_populates="node", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_graph_node_workspace_type", "workspace", "entity_type"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GraphNode {self.entity_type}:{self.name!r}>"


class GraphEdge(Base):
    """Aresta/Relacionamento direcionado no Grafo de Conhecimento."""

    __tablename__ = "graph_edge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace: Mapped[str] = mapped_column(String(255), default="default", nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_node.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_node.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # REFERENCIA, DEPENDE, AFETA, etc.
    layer: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Explicit, 2=Vector, 3=LLM
    weight: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    edge_metadata: Mapped[dict] = mapped_column("metadata", JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_node: Mapped[GraphNode] = relationship(
        "GraphNode", foreign_keys=[source_id], back_populates="outgoing_edges"
    )
    target_node: Mapped[GraphNode] = relationship(
        "GraphNode", foreign_keys=[target_id], back_populates="incoming_edges"
    )

    __table_args__ = (
        Index("ix_graph_edge_source", "source_id", "relation_type"),
        Index("ix_graph_edge_target", "target_id", "relation_type"),
        Index("ix_graph_edge_workspace_layer", "workspace", "layer"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GraphEdge {self.source_id} -[{self.relation_type}]-> {self.target_id}>"


class GraphChunkMapping(Base):
    """Mapeamento entre um nó do Grafo e um chunk de texto/código/documento."""

    __tablename__ = "graph_chunk_mapping"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_node.id", ondelete="CASCADE"), nullable=False
    )
    chunk_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # 'code', 'note', 'document'
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0, nullable=False)

    __table_args__ = (
        Index("ix_graph_chunk_mapping_node", "node_id"),
        Index("ix_graph_chunk_mapping_chunk", "chunk_id", "chunk_type"),
    )


class GraphMetrics(Base):
    """Métricas de relevância e centralidade para nós do grafo."""

    __tablename__ = "graph_metrics"

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_node.id", ondelete="CASCADE"), primary_key=True
    )
    workspace: Mapped[str] = mapped_column(String(255), nullable=False)
    in_degree: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    out_degree: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pagerank: Mapped[float] = mapped_column(Numeric(10, 8), default=0.0, nullable=False)
    betweenness: Mapped[float] = mapped_column(Numeric(10, 8), default=0.0, nullable=False)
    community_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_orphan: Mapped[bool] = mapped_column(
        Boolean, Computed("in_degree = 0 AND out_degree = 0", persisted=True), nullable=False
    )
    last_calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    node: Mapped[GraphNode] = relationship("GraphNode", back_populates="metrics")

    __table_args__ = (Index("ix_graph_metrics_workspace_pagerank", "workspace", "pagerank"),)


class ProjectRecord(Base):
    """Cadastro persistido e centralizado de projetos no Eltanix Coder IDE."""

    __tablename__ = "project_record"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    git_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    budget_limit_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProjectRecord {self.slug} ({self.name!r})>"


class AppUser(Base):
    """Usuário da plataforma (ver `auth/service.py`). `is_admin` é o dono da
    instância; papel por projeto vive em `ProjectMember`, ver `auth/rbac.py`."""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Dono da instância — pode criar outros usuários e gerencia membro de
    # qualquer projeto, não só os que integra via `ProjectMember`. O usuário
    # seed (`AuthService.ensure_seed_user`) é sempre o primeiro admin (ver
    # migração 0021); qualquer usuário criado depois começa `False`.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppUser {self.username}>"


class ProjectMember(Base):
    """Papel de um usuário num projeto — lido/escrito por `auth/rbac.py` e
    `auth/store.py`, aplicado por rota em `api/routes/*.py`. `role` é string
    livre (`owner`/`editor`/`viewer`), sem enum nativo do Postgres — mesmo
    padrão de `Skill.category`/`AuditLogEntry.risk_level`: adicionar um papel
    novo não deve exigir migração."""

    __tablename__ = "project_member"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_record.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), default="owner", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_project_member_project_user", "project_id", "user_id", unique=True),
        Index("ix_project_member_user", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProjectMember project={self.project_id} user={self.user_id} role={self.role!r}>"


class AuthSession(Base):
    """Sessão de login ativa. Guarda o hash do token, nunca o token em claro —
    mesmo princípio de `hmac.compare_digest` que `require_api_key` já usa para a
    chave de API de serviço."""

    __tablename__ = "auth_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthSession user={self.user_id}>"


class UserMfa(Base):
    """Segundo fator (TOTP) de um usuário. 1:1 com `app_user` — a ausência de
    linha é o estado "MFA não configurado"; nada muda para quem não ativou.

    `secret` (base32) vai cifrado em repouso com AES-256-GCM quando
    `ELTANIX_MFA_SECRET_KEY` está definida (F-7 de `docs/security_review_2026-08.md`,
    ver `auth/secret_box.py`); sem a chave, fica em claro como antes. O envelope
    cifrado é maior que o base32 cru — daí `String(255)`.
    `recovery_codes` guarda só o `sha256` de cada código de uso único (alta
    entropia, mesmo critério do token de sessão em `AuthSession`).
    """

    __tablename__ = "user_mfa"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    # False = segredo gerado no `setup` mas ainda não confirmado por um código
    # válido. Só `enabled=True` passa a exigir 2º fator no login.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recovery_codes: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserMfa user={self.user_id} enabled={self.enabled}>"


class ChatTrajectory(Base):
    """Armazena o fluxo e telemetria completa de uma sessão de chat do agente para análise por ML."""

    __tablename__ = "chat_trajectory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    user_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="success", nullable=False)
    failure_category: Mapped[str] = mapped_column(
        String(64), default="NONE", nullable=False, index=True
    )
    trajectory_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    embedding: Mapped[list | None] = mapped_column(VECTOR_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatTrajectory session={self.session_id} category={self.failure_category}>"


class FailureCluster(Base):
    """Agrupa falhas semelhantes detectadas por agrupamento semântico (clustering)."""

    __tablename__ = "failure_cluster"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    failure_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    centroid_embedding: Mapped[list | None] = mapped_column(VECTOR_TYPE, nullable=True)
    sample_trajectory_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FailureCluster name={self.name!r} count={self.occurrence_count}>"


class CorrectionProposal(Base):
    """Proposta de correção gerada pela IA/ML para mitigar falhas mapeadas na IDE."""

    __tablename__ = "correction_proposal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("failure_cluster.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    diff_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CorrectionProposal title={self.title!r} type={self.proposal_type} status={self.status}>"


class CompletionEvent(Base):
    """Desfecho de uma sugestão de autocompletar inline (ghost text), ADR 0014.

    Custo e latência de cada chamada já vivem em `request_log` via o router
    (ADR 0001); o que falta lá é o desfecho — a sugestão foi aceita, rejeitada
    ou ignorada, e quantos chars o humano de fato aproveitou. Esse é o número
    que diz se o autocompletar presta.

    **Não** guarda prefixo/sufixo nem o texto da sugestão: só contagem de
    chars, linguagem e modelo. O conteúdo do arquivo não precisa ser
    reespelhado aqui.
    """

    __tablename__ = "completion_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    suggestion_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # accepted | rejected | ignored — `ignored` é a sugestão que ficou visível e
    # o timeout de exibição disparou sem o usuário aceitar nem digitar por cima.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    shown_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chars_suggested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chars_accepted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompletionEvent suggestion={self.suggestion_id} outcome={self.outcome}>"
