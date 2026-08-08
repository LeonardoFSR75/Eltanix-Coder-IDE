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

    source: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), default="chat", nullable=False)
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

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
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
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
    project_slug: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
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


class GraphNode(Base):
    """Nó/Entidade do Grafo de Conhecimento do Segundo Cérebro (Graphify)."""

    __tablename__ = "graph_node"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace: Mapped[str] = mapped_column(String(255), default="default", nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)  # Note, Concept, Module, Class, ADR, etc.
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
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

    __table_args__ = (
        Index("ix_graph_node_workspace_type", "workspace", "entity_type"),
    )

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
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)  # REFERENCIA, DEPENDE, AFETA, etc.
    layer: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Explicit, 2=Vector, 3=LLM
    weight: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    edge_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_node: Mapped[GraphNode] = relationship("GraphNode", foreign_keys=[source_id], back_populates="outgoing_edges")
    target_node: Mapped[GraphNode] = relationship("GraphNode", foreign_keys=[target_id], back_populates="incoming_edges")

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
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'code', 'note', 'document'
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

    __table_args__ = (
        Index("ix_graph_metrics_workspace_pagerank", "workspace", "pagerank"),
    )


class ProjectRecord(Base):
    """Cadastro persistido e centralizado de projetos no SicoobitoCode."""

    __tablename__ = "project_record"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    git_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    budget_limit_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProjectRecord {self.slug} ({self.name!r})>"


class AppUser(Base):
    """Usuário da plataforma. Etapa 1 do login (ver `auth/service.py`): um só
    usuário seed por enquanto, sem RBAC — a tabela existe separada de qualquer
    outra coisa exatamente para que multiusuário/permissão por projeto seja uma
    tabela de associação nova (`project_member`) no futuro, não uma reescrita."""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppUser {self.username}>"


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


