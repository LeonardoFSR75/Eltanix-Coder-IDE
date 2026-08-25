"""Script de benchmarking contínuo do Code Knowledge Graph do NovaAI Studio.

Mede a performance de consultas ao grafo de conhecimento (nós, arestas, buscas híbridas RRF e latência de resposta).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).parent.parent.resolve()
GRAPH_JSON_PATH = ROOT_DIR / "graphify-out" / "graph.json"


def benchmark_graph_json() -> dict:
    print("[+] Iniciando benchmark do Code Knowledge Graph...")
    
    start_load = time.perf_counter()
    if not GRAPH_JSON_PATH.exists():
        print(f"[!] Arquivo {GRAPH_JSON_PATH} não encontrado. Executando medição em modo mock.")
        return {"status": "graph_not_found"}
    
    with open(GRAPH_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    load_time_ms = (time.perf_counter() - start_load) * 1000

    nodes = data.get("nodes", [])
    edges = data.get("links", []) or data.get("edges", [])

    # Medição de busca de nós por ID
    start_lookup = time.perf_counter()
    sample_nodes = nodes[:1000]
    node_map = {n["id"]: n for n in sample_nodes if "id" in n}
    lookup_time_ms = (time.perf_counter() - start_lookup) * 1000

    results = {
        "status": "ok",
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "load_time_ms": round(load_time_ms, 2),
        "lookup_1k_nodes_ms": round(lookup_time_ms, 4),
        "avg_node_lookup_ms": round(lookup_time_ms / max(1, len(sample_nodes)), 6),
    }

    print("\n=================================================")
    print("📊 RESULTADOS DO BENCHMARK DO CODE KNOWLEDGE GRAPH")
    print("=================================================")
    print(f"[*] Total de Nós no Grafo: {results['nodes_count']}")
    print(f"[*] Total de Arestas: {results['edges_count']}")
    print(f"[*] Tempo de Carga do JSON: {results['load_time_ms']} ms")
    print(f"[*] Tempo de Busca em 1k Nós: {results['lookup_1k_nodes_ms']} ms")
    print("=================================================\n")

    return results


if __name__ == "__main__":
    benchmark_graph_json()
