"""Testes unitários e de integração para a Engine de Analytics ML e Auto-Diagnósticos da IDE."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sicoobito.analytics.diagnostics.correction_generator import CorrectionProposalGenerator
from sicoobito.analytics.diagnostics.rca_engine import RCAEngine
from sicoobito.analytics.ingestion import TrajectoryIngestor, sanitize_text
from sicoobito.analytics.models.classifier import FailureCategory, TrajectoryClassifier
from sicoobito.analytics.models.clustering import UnsupervisedClusterer, cosine_distance


def test_sanitize_text_credentials() -> None:
    raw_text = "API Key: sk-proj-1234567890abcdef12345678 e Bearer eyJhbGciOiJIUzI1Ni"
    sanitized = sanitize_text(raw_text)
    assert "sk-proj-1234567890abcdef12345678" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized


def test_trajectory_ingestor_metrics() -> None:
    session_id = "test-session-123"
    prompt = "Corrija o bug no endpoint /login com token sk-12345678901234567890"
    steps = [
        {
            "tokens": 500,
            "tool_calls": [
                {"name": "run_command", "status": "error", "error": "Permission denied"},
                {"name": "run_command", "status": "error", "error": "Permission denied"},
            ],
        }
    ]

    result = TrajectoryIngestor.process_raw_session(session_id, prompt, steps)
    assert result["session_id"] == session_id
    assert "sk-1234567890" not in result["user_prompt"]
    assert result["tool_calls_count"] == 2
    assert result["tool_errors_count"] == 2
    assert result["metrics"]["tool_error_rate"] == 1.0
    assert result["metrics"]["loop_coefficient"] == 1.0


def test_trajectory_classifier_tool_failure() -> None:
    trajectory = {
        "user_prompt": "Executar script",
        "status": "failed",
        "tool_calls_count": 3,
        "tool_errors_count": 2,
        "metrics": {"context_saturation": 0.1, "loop_coefficient": 0.0},
        "trajectory_data": {
            "steps": [{"tool_calls": [{"name": "run_command", "error": "SyntaxError"}]}]
        },
    }

    category = TrajectoryClassifier.classify(trajectory)
    assert category == FailureCategory.TOOL_EXECUTION_FAILURE


def test_trajectory_classifier_context_overflow() -> None:
    trajectory = {
        "user_prompt": "Refatoração ampla",
        "status": "failed",
        "tool_calls_count": 1,
        "tool_errors_count": 0,
        "metrics": {"context_saturation": 0.98, "loop_coefficient": 0.0},
        "trajectory_data": {"steps": []},
    }

    category = TrajectoryClassifier.classify(trajectory)
    assert category == FailureCategory.CONTEXT_TRUNCATION_OR_OVERFLOW


def test_cosine_distance_and_clustering() -> None:
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.1, 0.0]
    vec_c = [0.0, 1.0, 0.0]

    dist_ab = cosine_distance(vec_a, vec_b)
    dist_ac = cosine_distance(vec_a, vec_c)
    assert dist_ab < dist_ac

    trajectories = [
        {"id": "1", "embedding": vec_a, "user_prompt": "Erro 1", "failure_category": "TOOL_ERROR"},
        {"id": "2", "embedding": vec_b, "user_prompt": "Erro 2", "failure_category": "TOOL_ERROR"},
        {"id": "3", "embedding": vec_c, "user_prompt": "Erro 3", "failure_category": "RAG_MISS"},
    ]

    clusters = UnsupervisedClusterer.cluster_trajectories(trajectories, distance_threshold=0.3)
    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_rca_and_proposal_generation() -> None:
    mock_router = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "A causa raiz foi erro de sintaxe na sandbox do Docker."
    mock_router.complete = AsyncMock(return_value=mock_response)

    rca_engine = RCAEngine(mock_router)
    generator = CorrectionProposalGenerator(mock_router)

    trajectory = {"user_prompt": "Rodar comando", "trajectory_data": {"steps": []}}
    rca_res = await rca_engine.analyze_failure(trajectory, FailureCategory.TOOL_EXECUTION_FAILURE)

    assert rca_res["category"] == FailureCategory.TOOL_EXECUTION_FAILURE
    assert rca_res["severity"] == "high"

    proposal = await generator.generate_proposal(trajectory, rca_res)
    assert proposal["proposal_type"] == "TOOL_PATCH"
    assert "target_file" in proposal
    assert proposal["confidence_score"] > 0.8


@pytest.mark.asyncio
async def test_analytics_batch_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from sicoobito.analytics.worker import AnalyticsBatchWorker

    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_res)

    class DummyAsyncContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(
        "sicoobito.analytics.worker.session_scope", lambda: DummyAsyncContextManager()
    )

    mock_router = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Falha no comando de sandbox."
    mock_router.complete = AsyncMock(return_value=mock_response)

    worker = AnalyticsBatchWorker(mock_router)
    res = await worker.run_batch_cycle()
    assert res["processed_count"] == 0
    assert res["clusters_created"] == 0
