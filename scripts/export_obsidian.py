"""Script para gerar a base de conhecimento do Obsidian e o grafo visual HTML
a partir do graphify-out/graph.json com sanitização estrita para caminhos Windows.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Configura stdout para UTF-8 no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import networkx as nx
from networkx.readwrite import json_graph

import graphify.export as exp

# Permite renderização completa no HTML de todos os nós indexados
exp.MAX_NODES_FOR_VIZ = 20000


def sanitize_filename(name: str) -> str:
    """Sanitiza o nome do arquivo para compatibilidade universal com Windows, Linux e macOS."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    clean = clean.strip(' ._')
    if len(clean) > 120:
        clean = clean[:117] + '...'
    return clean or 'unnamed_node'


def run_export() -> None:
    graph_path = Path("graphify-out/graph.json")
    if not graph_path.exists():
        print("graph.json não encontrado.")
        return

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    G = json_graph.node_link_graph(data, edges="links")

    communities: dict[int, list[str]] = {}
    for node in data.get("nodes", []):
        cid = int(node.get("community") or 0)
        communities.setdefault(cid, []).append(node["id"])

    labels: dict[int, str] = {}
    labels_file = Path("graphify-out/.graphify_labels.json")
    if labels_file.exists():
        raw_labels = json.loads(labels_file.read_text(encoding="utf-8"))
        labels = {int(k): v for k, v in raw_labels.items()}

    out_obsidian = Path("graphify-out/obsidian")
    out_obsidian.mkdir(parents=True, exist_ok=True)

    # 1. Export HTML Visualizer
    html_out = Path("graphify-out/graph.html")
    try:
        exp.to_html(
            G,
            communities,
            output_path=str(html_out),
            community_labels=labels,
            project_name="SicoobitoCode Knowledge Graph",
        )
        print(f"[OK] Visualizador HTML atualizado em {html_out}")
    except Exception as exc:
        print(f"[Aviso] Ao gerar HTML: {exc}")

    # 2. Export individual node files with Windows-safe sanitization
    nodes_written = 0
    symbols_dir = out_obsidian / "05 - 💻 Código & Símbolos"
    symbols_dir.mkdir(parents=True, exist_ok=True)

    for nid, ndata in G.nodes(data=True):
        label = str(ndata.get("label") or nid)
        fname = sanitize_filename(label) + ".md"
        node_file = symbols_dir / fname

        community_id = ndata.get("community", 0)
        comm_name = labels.get(community_id, f"Comunidade {community_id}")

        neighbors_in = [
            f"[[{sanitize_filename(str(G.nodes[u].get('label', u)))}]]"
            for u in G.predecessors(nid)
            if u in G.nodes
        ] if G.is_directed() else []

        neighbors_out = [
            f"[[{sanitize_filename(str(G.nodes[v].get('label', v)))}]]"
            for v in (G.successors(nid) if G.is_directed() else G.neighbors(nid))
            if v in G.nodes
        ]

        file_type = ndata.get("file_type", "code")
        source_file = ndata.get("source_file") or ndata.get("file", "")

        lines = [
            "---",
            f'title: "{label.replace('"', '\\"')}"',
            f'type: "{file_type}"',
            f"community: {community_id}",
            f'community_name: "{comm_name}"',
            "tags:",
            "  - graphify/node",
            f"  - community/{community_id}",
            "---",
            "",
            f"# {label}",
            "",
            f"> **Comunidade**: [[{comm_name}]] | **Tipo**: `{file_type}`" + (f" | **Arquivo**: `{source_file}`" if source_file else ""),
            "",
        ]

        summary = ndata.get("summary") or ndata.get("description")
        if summary:
            lines.extend(["## Resumo", "", summary, ""])

        if neighbors_out:
            lines.extend(["## Conexões & Dependências", ""])
            for link in neighbors_out[:30]:
                lines.append(f"- {link}")
            lines.append("")

        if neighbors_in:
            lines.extend(["## Usado / Referenciado Por", ""])
            for link in neighbors_in[:30]:
                lines.append(f"- {link}")
            lines.append("")

        try:
            node_file.write_text("\n".join(lines), encoding="utf-8")
            nodes_written += 1
        except Exception:
            pass

    print(f"[OK] {nodes_written} notas de entidades/símbolos atualizadas no Obsidian!")


if __name__ == "__main__":
    run_export()
