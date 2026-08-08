"""Pipeline de Indexação em 10 Etapas do Graphify Engine."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sicoobito.context.scanner import scan
from sicoobito.graphify.pipeline.l1_wikilinks import (
    extract_python_imports,
    extract_tags,
    extract_ts_imports,
    extract_wikilinks,
)
from sicoobito.graphify.schema import GraphEdgeCreate, GraphNodeCreate
from sicoobito.graphify.store import GraphStore


class GraphIndexer:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    async def run_pipeline(
        self, source_type: str, payload: dict[str, Any], *, compute_metrics: bool = True
    ) -> dict[str, Any]:
        """Executa a pipeline para transformar conteúdo em Entidades & Arestas."""
        workspace = payload.get("workspace", "default")
        title = payload.get("title") or payload.get("filename") or payload.get("path") or "Untitled"
        content = payload.get("content", "")

        tags = extract_tags(content)
        canonical_id = f"{source_type}:{title}"

        # Determine entity_type formatting
        type_label = source_type.capitalize()
        if source_type in ("md", "note"):
            type_label = "Note"
        elif source_type in ("py", "python", "ts", "tsx", "js", "jsx", "code"):
            type_label = "Module"
        elif source_type in ("adr",):
            type_label = "ADR"

        main_node_in = GraphNodeCreate(
            workspace=workspace,
            entity_type=type_label,
            name=title,
            canonical_id=canonical_id,
            properties={"tags": tags, "source_type": source_type},
            summary=content[:300] if content else "",
        )
        main_node = await self.store.upsert_node(main_node_in)

        created_edges = 0

        # Wikilinks (Layer 1)
        if source_type in ("note", "md", "adr"):
            wikilinks = extract_wikilinks(content)
            for target_title in wikilinks:
                target_canonical = f"note:{target_title}"
                target_node_in = GraphNodeCreate(
                    workspace=workspace,
                    entity_type="Note",
                    name=target_title,
                    canonical_id=target_canonical,
                    properties={"stub": True},
                    summary=f"Nota referenciada por {title}",
                )
                target_node = await self.store.upsert_node(target_node_in)

                edge_in = GraphEdgeCreate(
                    workspace=workspace,
                    source_id=main_node.id,
                    target_id=target_node.id,
                    relation_type="REFERENCIA",
                    layer=1,
                    weight=1.0,
                    evidence=f"[[{target_title}]] em {title}",
                )
                await self.store.add_edge(edge_in)
                created_edges += 1

        # Code Imports (Layer 1 - Python)
        if source_type in ("code", "file", "python", "py"):
            imports = extract_python_imports(content)
            for mod in imports:
                mod_canonical = f"module:{mod}"
                mod_node_in = GraphNodeCreate(
                    workspace=workspace,
                    entity_type="Module",
                    name=mod,
                    canonical_id=mod_canonical,
                    properties={"imported": True},
                )
                mod_node = await self.store.upsert_node(mod_node_in)

                edge_in = GraphEdgeCreate(
                    workspace=workspace,
                    source_id=main_node.id,
                    target_id=mod_node.id,
                    relation_type="DEPENDE",
                    layer=1,
                    weight=0.9,
                    evidence=f"import {mod} em {title}",
                )
                await self.store.add_edge(edge_in)
                created_edges += 1

        # Code Imports (Layer 1 - TS / JS)
        if source_type in ("ts", "tsx", "js", "jsx", "typescript", "javascript"):
            imports = extract_ts_imports(content)
            for mod in imports:
                mod_canonical = f"module:{mod}"
                mod_node_in = GraphNodeCreate(
                    workspace=workspace,
                    entity_type="Module",
                    name=mod,
                    canonical_id=mod_canonical,
                    properties={"imported": True},
                )
                mod_node = await self.store.upsert_node(mod_node_in)

                edge_in = GraphEdgeCreate(
                    workspace=workspace,
                    source_id=main_node.id,
                    target_id=mod_node.id,
                    relation_type="DEPENDE",
                    layer=1,
                    weight=0.9,
                    evidence=f"import {mod} em {title}",
                )
                await self.store.add_edge(edge_in)
                created_edges += 1

        # Tags como Conceitos (Layer 1)
        for tag in tags:
            tag_canonical = f"concept:{tag}"
            tag_node_in = GraphNodeCreate(
                workspace=workspace,
                entity_type="Concept",
                name=f"#{tag}",
                canonical_id=tag_canonical,
                properties={"is_tag": True},
            )
            tag_node = await self.store.upsert_node(tag_node_in)

            edge_in = GraphEdgeCreate(
                workspace=workspace,
                source_id=main_node.id,
                target_id=tag_node.id,
                relation_type="RELACIONADO",
                layer=1,
                weight=0.8,
                evidence=f"#{tag} em {title}",
            )
            await self.store.add_edge(edge_in)
            created_edges += 1

        metrics_summary = None
        if compute_metrics:
            metrics_summary = await self.store.compute_metrics(workspace)

        return {
            "status": "success",
            "node_id": str(main_node.id),
            "canonical_id": canonical_id,
            "edges_created": created_edges,
            "metrics": metrics_summary,
        }

    async def index_directory(self, root_path: Path, workspace: str = "default") -> dict[str, Any]:
        """Varre um diretório do projeto e indexa todos os arquivos no Grafo de Conhecimento."""
        if not await asyncio.to_thread(root_path.is_dir):
            return {"status": "error", "message": f"Diretório não existe: {root_path}"}

        scanned_files = await asyncio.to_thread(lambda: list(scan(root_path)))
        indexed_count = 0
        total_edges = 0

        for scanned in scanned_files:
            ext = scanned.absolute.suffix.lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".exe", ".dll", ".map"):
                continue

            try:
                content = await asyncio.to_thread(
                    lambda p=scanned.absolute: p.read_text(encoding="utf-8", errors="ignore")
                )
            except Exception:
                continue

            if not content.strip():
                continue

            source_type = "file"
            if ext in (".md", ".markdown"):
                source_type = "adr" if "adr" in scanned.path.lower() else "note"
            elif ext == ".py":
                source_type = "python"
            elif ext in (".ts", ".tsx"):
                source_type = "typescript"
            elif ext in (".js", ".jsx"):
                source_type = "javascript"

            res = await self.run_pipeline(
                source_type=source_type,
                payload={
                    "workspace": workspace,
                    "title": scanned.path,
                    "filename": scanned.path,
                    "content": content,
                },
                compute_metrics=False,  # Otimização: métricas apenas 1x no final do lote!
            )
            indexed_count += 1
            total_edges += res.get("edges_created", 0)

        # Recalcula métricas e PageRank apenas UMA vez após indexar todos os arquivos do lote
        metrics_summary = await self.store.compute_metrics(workspace)

        return {
            "status": "success",
            "workspace": workspace,
            "nodes_indexed": indexed_count,
            "total_edges": total_edges,
            "metrics": metrics_summary,
        }
