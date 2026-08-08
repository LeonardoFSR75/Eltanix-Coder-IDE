"""Schemas Pydantic para o Módulo Graphify (Knowledge Graph & GraphRAG)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GraphNodeBase(BaseModel):
    workspace: str = "default"
    entity_type: str = Field(..., description="Tipo de entidade (Note, Concept, Module, Class, ADR, etc.)")
    name: str = Field(..., description="Nome de exibição do nó")
    canonical_id: str = Field(..., description="ID determinístico único por workspace")
    properties: dict = Field(default_factory=dict)
    summary: str | None = None


class GraphNodeCreate(GraphNodeBase):
    embedding: list[float] | None = None


class GraphNodeRead(GraphNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    pagerank: float | None = None
    in_degree: int | None = None
    out_degree: int | None = None
    is_orphan: bool | None = None


class GraphEdgeBase(BaseModel):
    workspace: str = "default"
    source_id: UUID
    target_id: UUID
    relation_type: str = Field(..., description="Tipo de relacionamento (REFERENCIA, DEPENDE, AFETA, etc.)")
    layer: int = Field(1, description="Camada da aresta: 1=Explicit, 2=Vector, 3=LLM")
    weight: float = Field(1.0, ge=0.0, le=1.0)
    evidence: str | None = None
    edge_metadata: dict = Field(default_factory=dict)


class GraphEdgeCreate(GraphEdgeBase):
    pass


class GraphEdgeRead(GraphEdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class SubgraphResponse(BaseModel):
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]


class GraphRAGQueryRequest(BaseModel):
    query: str
    workspace: str = "default"
    top_k: int = 10
    max_hops: int = 2


class GraphRAGResult(BaseModel):
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]
    chunks: list[dict]
    query: str
    total_nodes: int


class GraphMetricsSummary(BaseModel):
    workspace: str
    total_nodes: int
    total_edges: int
    orphan_nodes_count: int
    orphan_percentage: float
    density: float
    top_hotspots: list[GraphNodeRead]
