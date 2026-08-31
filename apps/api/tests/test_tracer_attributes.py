"""Atributos do span de RAG.

Sem eles um span só diz "demorou X e não deu erro", o que não distingue uma
busca boa de uma que degradou para full-text puro e devolveu qualquer coisa —
e é justamente essa diferença que se procura quando a resposta veio ruim.
"""

from __future__ import annotations

from eltanix.telemetry.tracer import TraceEntry, TraceRecorder


def test_record_guarda_os_atributos() -> None:
    recorder = TraceRecorder()
    recorder.record(
        kind="rag",
        name="context",
        latency_ms=12.3,
        status="ok",
        attributes={"hits": 8, "degraded_to_fulltext": False, "top_score": 0.031},
    )

    (entry,) = recorder.recent()
    assert entry.attributes["hits"] == 8
    assert entry.attributes["degraded_to_fulltext"] is False


def test_atributo_com_nome_reservado_nao_derruba_o_log() -> None:
    """`name` e `status` já são argumentos do log do span: repassá-los como
    atributo levantaria TypeError dentro de quem chamou `record`."""
    recorder = TraceRecorder()
    recorder.record(
        kind="rag",
        name="documents",
        latency_ms=1.0,
        status="ok",
        attributes={"name": "colide", "status": "colide", "hits": 1},
    )

    (entry,) = recorder.recent()
    assert entry.name == "documents"
    assert entry.attributes["name"] == "colide"


def test_span_sem_atributos_continua_valido() -> None:
    recorder = TraceRecorder()
    recorder.record(kind="tool", name="read_file", latency_ms=2.0, status="ok")

    (entry,) = recorder.recent()
    assert entry.attributes == {}
    assert entry.to_dict()["attributes"] == {}


def test_roundtrip_de_serializacao_preserva_atributos() -> None:
    original = TraceEntry(
        ts=1.0,
        kind="rag",
        name="notes",
        latency_ms=5.0,
        status="ok",
        attributes={"hits": 3},
    )

    assert TraceEntry.from_dict(original.to_dict()).attributes == {"hits": 3}


def test_otlp_tipa_booleano_como_booleano() -> None:
    """`True` é instância de `int` em Python: sem o teste de bool primeiro, um
    atributo booleano sairia como intValue e chegaria com o tipo errado em
    quem consome o trace."""
    entry = TraceEntry(
        ts=1.0,
        kind="rag",
        name="context",
        latency_ms=5.0,
        status="ok",
        attributes={"degraded_to_fulltext": True, "hits": 4, "top_score": 0.5, "model": "nomic"},
    )

    atributos = entry.to_otlp_json()["scopeSpans"][0]["spans"][0]["attributes"]
    por_chave = {a["key"]: a["value"] for a in atributos}

    assert por_chave["eltanix.degraded_to_fulltext"] == {"boolValue": True}
    assert por_chave["eltanix.hits"] == {"intValue": "4"}
    assert por_chave["eltanix.top_score"] == {"doubleValue": 0.5}
    assert por_chave["eltanix.model"] == {"stringValue": "nomic"}
