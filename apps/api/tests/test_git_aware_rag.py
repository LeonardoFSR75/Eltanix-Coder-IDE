"""Git-Aware RAG (Fase 4) — parte pura do re-rank em `context/git_aware.py`.

Unitário, sem banco nem git: exercita `rerank` e o efeito dos sinais de
co-mudança e recência sobre o score. O caminho com Postgres/pgvector real
fica em `test_hybrid_search.py` (gated por `DATABASE_URL_TEST`).
"""

from __future__ import annotations

from eltanix.context.git_aware import (
    _NEIGHBOR_FACTOR,
    _RECENCY_HALFLIFE_DAYS,
    RecencySignal,
    rerank,
)
from eltanix.context.store import SearchHit


def _hit(path: str, line: int, score: float, *, symbol: str | None = None) -> SearchHit:
    return SearchHit(
        path=path,
        symbol=symbol,
        parent=None,
        kind="function",
        start_line=line,
        end_line=line + 5,
        content=f"# {path}:{line}",
        language="python",
        token_count=20,
        score=score,
    )


_NO_SIGNAL = RecencySignal(co_changed={}, blame_age_days={})


def test_rerank_dedupes_base_and_neighbors_by_path_and_line():
    base = [_hit("a.py", 1, 0.9), _hit("b.py", 10, 0.5)]
    neighbors = [_hit("a.py", 1, 0.4), _hit("c.py", 3, 0.3)]  # a.py:1 é duplicata
    out = rerank(base, neighbors, _NO_SIGNAL, limit=10)
    keys = [(h.path, h.start_line) for h in out]
    assert keys == [("a.py", 1), ("b.py", 10), ("c.py", 3)]


def test_neighbor_never_outranks_its_parent_without_signals():
    base = [_hit("a.py", 1, 0.5)]
    neighbors = [_hit("z.py", 1, 0.5 * _NEIGHBOR_FACTOR)]
    out = rerank(base, neighbors, _NO_SIGNAL, limit=10)
    assert out[0].path == "a.py"
    assert out[1].score < out[0].score


def test_cochange_boosts_the_co_changed_path():
    base = [_hit("a.py", 1, 0.50), _hit("b.py", 1, 0.48)]
    signal = RecencySignal(co_changed={"b.py": 8}, blame_age_days={})
    out = rerank(base, [], signal, limit=10)
    assert out[0].path == "b.py"  # boost virou a ordem


def test_recent_code_scores_above_identical_but_old_code():
    base = [_hit("old.py", 1, 0.50), _hit("new.py", 1, 0.50)]
    signal = RecencySignal(
        co_changed={},
        blame_age_days={"new.py": 1.0, "old.py": _RECENCY_HALFLIFE_DAYS * 6},
    )
    out = rerank(base, [], signal, limit=10)
    assert out[0].path == "new.py"
    assert out[0].score > out[1].score


def test_limit_truncates_after_rerank():
    base = [_hit(f"f{i}.py", 1, 1.0 - i * 0.05) for i in range(10)]
    out = rerank(base, [], _NO_SIGNAL, limit=3)
    assert len(out) == 3
    assert [h.path for h in out] == ["f0.py", "f1.py", "f2.py"]


def test_cochange_peak_is_the_max_count():
    assert RecencySignal(co_changed={"x": 2, "y": 9}, blame_age_days={}).cochange_peak == 9
    assert RecencySignal(co_changed={}, blame_age_days={}).cochange_peak == 0
