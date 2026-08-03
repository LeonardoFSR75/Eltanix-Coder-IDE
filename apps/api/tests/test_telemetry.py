"""TraceRecorder é só um buffer circular — sem I/O, sem Postgres/Redis."""

from __future__ import annotations

from sicoobito.telemetry.tracer import TraceRecorder


def test_recent_is_empty_without_records():
    recorder = TraceRecorder()
    assert recorder.recent() == []


def test_record_appears_in_recent_most_recent_first():
    recorder = TraceRecorder()
    recorder.record(kind="tool", name="write_file", latency_ms=12.3, status="ok")
    recorder.record(kind="rag", name="documents", latency_ms=45.6, status="error", error="boom")

    entries = recorder.recent()
    assert [e.name for e in entries] == ["documents", "write_file"]
    assert entries[0].kind == "rag"
    assert entries[0].status == "error"
    assert entries[0].error == "boom"
    assert entries[1].latency_ms == 12.3


def test_recent_respects_limit():
    recorder = TraceRecorder()
    for i in range(10):
        recorder.record(kind="tool", name=f"tool_{i}", latency_ms=1.0, status="ok")

    assert len(recorder.recent(limit=3)) == 3
    assert [e.name for e in recorder.recent(limit=3)] == ["tool_9", "tool_8", "tool_7"]


def test_buffer_is_circular_and_drops_oldest():
    recorder = TraceRecorder(maxlen=2)
    recorder.record(kind="tool", name="first", latency_ms=1.0, status="ok")
    recorder.record(kind="tool", name="second", latency_ms=1.0, status="ok")
    recorder.record(kind="tool", name="third", latency_ms=1.0, status="ok")

    names = [e.name for e in recorder.recent()]
    assert names == ["third", "second"]


def test_error_is_truncated():
    recorder = TraceRecorder()
    recorder.record(kind="tool", name="x", latency_ms=1.0, status="error", error="e" * 1000)
    assert len(recorder.recent()[0].error) == 300
