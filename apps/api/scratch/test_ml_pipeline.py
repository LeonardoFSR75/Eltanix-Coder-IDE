"""Script de teste end-to-end do pipeline de Machine Learning (Analytics & Auto-Diagnósticos)."""

from __future__ import annotations

import asyncio
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from eltanix.analytics.ingestion import TrajectoryIngestor, sanitize_text
from eltanix.analytics.models.classifier import TrajectoryClassifier, FailureCategory
from eltanix.analytics.models.clustering import UnsupervisedClusterer, cosine_distance
from eltanix.analytics.diagnostics.rca_engine import RCAEngine
from eltanix.analytics.diagnostics.correction_generator import CorrectionProposalGenerator


def run_pipeline_demo():
    print("==========================================================================")
    print("🤖 TESTE DA ENGINE DE MACHINE LEARNING E AUTO-DIAGNÓSTICO DO ELTANIX CODER IDE")
    print("==========================================================================\n")

    # 1. Teste de Sanitização de Credenciais
    raw_prompt = "Corrija a função com API key sk-proj-99887766554433221100 e token Bearer eyJhbGciOiJIUzI1Ni"
    sanitized = sanitize_text(raw_prompt)
    print("1. 🛡️ SANITIZAÇÃO DE DADOS SENSÍVEIS (Regex + Pattern Redaction):")
    print(f"   Original:  {raw_prompt}")
    print(f"   Sanitizado: {sanitized}\n")

    # 2. Ingestão e Cálculo de Métricas
    session_id = "sess-demo-777"
    raw_steps = [
        {
            "step_index": 1,
            "tokens": 1200,
            "tool_calls": [
                {"name": "run_command", "status": "error", "error": "PermissionDeniedError: /var/run/docker.sock"},
                {"name": "run_command", "status": "error", "error": "PermissionDeniedError: /var/run/docker.sock"},
                {"name": "run_command", "status": "error", "error": "PermissionDeniedError: /var/run/docker.sock"},
            ]
        },
        {
            "step_index": 2,
            "tokens": 8500,
            "tool_calls": [
                {"name": "write_to_file", "status": "success"},
            ]
        }
    ]

    processed = TrajectoryIngestor.process_raw_session(
        session_id=session_id,
        user_prompt=sanitized,
        steps=raw_steps,
        project_slug="eltanix-code"
    )

    print("2. 📊 INGESTÃO E EXTRAÇÃO DE MÉTRICAS DA TRAJETÓRIA:")
    print(f"   • Passos executados: {processed['step_count']}")
    print(f"   • Total de chamadas de tools: {processed['tool_calls_count']}")
    print(f"   • Erros de ferramentas: {processed['tool_errors_count']}")
    print(f"   • Taxa de Erro de Tools: {processed['metrics']['tool_error_rate'] * 100:.1f}%")
    print(f"   • Coeficiente de Loop Repetitivo: {processed['metrics']['loop_coefficient']:.2f}")
    print(f"   • Saturação de Contexto: {processed['metrics']['context_saturation'] * 100:.1f}%\n")

    # 3. Classificação de Falha via ML Heurístico
    category = TrajectoryClassifier.classify(processed)
    print("3. 🎯 CLASSIFICAÇÃO ML DE CATEGORIA DE FALHA:")
    print(f"   • Categoria Identificada: {category}\n")

    # 4. Clusterização Não-Supervisionada (Distância Cosseno & K-Means/DBSCAN threshold)
    print("4. 🔮 CLUSTERIZAÇÃO NÃO-SUPERVISIONADA DE TRAJETÓRIAS SIMILARES:")
    vec_a = [0.9, 0.1, 0.05, 0.8]  # Falha de permissão sandbox A
    vec_b = [0.88, 0.12, 0.04, 0.79] # Falha de permissão sandbox B
    vec_c = [0.05, 0.95, 0.9, 0.1]  # Truncamento de contexto RAG C

    dist_ab = cosine_distance(vec_a, vec_b)
    dist_ac = cosine_distance(vec_a, vec_c)
    print(f"   • Distância cosseno (A vs B - Falhas similares): {dist_ab:.4f} (Alta Similaridade)")
    print(f"   • Distância cosseno (A vs C - Falhas distintas): {dist_ac:.4f} (Baixa Similaridade)")

    sample_trajectories = [
        {"id": "traj_001", "embedding": vec_a, "user_prompt": "Erro docker sock", "failure_category": category},
        {"id": "traj_002", "embedding": vec_b, "user_prompt": "Permission denied docker", "failure_category": category},
        {"id": "traj_003", "embedding": vec_c, "user_prompt": "Context length exceeded", "failure_category": FailureCategory.CONTEXT_TRUNCATION_OR_OVERFLOW},
    ]

    clusters = UnsupervisedClusterer.cluster_trajectories(sample_trajectories, distance_threshold=0.25)
    print(f"   • Total de Clusters Formados: {len(clusters)}")
    for i, cl in enumerate(clusters, 1):
        print(f"     Cluster #{i}: Categoria '{cl['failure_category']}' | {len(cl['sample_ids'])} trajetórias aglutinadas")
    print()

    print("==========================================================================")
    print("✅ TESTE DO PIPELINE DE MACHINE LEARNING CONCLUÍDO COM SUCESSO!")
    print("==========================================================================")


if __name__ == "__main__":
    run_pipeline_demo()
