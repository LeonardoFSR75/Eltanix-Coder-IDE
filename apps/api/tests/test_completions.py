"""Parte pura do autocompletar inline (`context/completions.py`) — recorte de
contexto, montagem do prompt FIM-sobre-chat e limpeza da resposta do modelo.
A chamada de LLM real fica na rota (`POST /api/context/completions`)."""

from __future__ import annotations

from eltanix.context import completions


def test_clamp_context_trims_prefix_from_the_left_and_suffix_from_the_right():
    prefix = "P" * (completions.MAX_PREFIX_CHARS + 500) + "END"
    suffix = "START" + "S" * (completions.MAX_SUFFIX_CHARS + 500)
    clamped_prefix, clamped_suffix = completions.clamp_context(prefix, suffix)
    assert len(clamped_prefix) == completions.MAX_PREFIX_CHARS
    assert clamped_prefix.endswith("END")  # o que está colado no cursor sobrevive
    assert len(clamped_suffix) == completions.MAX_SUFFIX_CHARS
    assert clamped_suffix.startswith("START")


def test_clamp_context_leaves_small_context_untouched():
    assert completions.clamp_context("abc", "def") == ("abc", "def")


def test_build_messages_carries_prefix_suffix_path_and_language():
    msgs = completions.build_messages(
        prefix="def soma(a, b):\n    return ",
        suffix="\n\nprint(soma(1, 2))",
        path="calc.py",
        language="python",
    )
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert "calc.py" in user and "python" in user
    assert "def soma(a, b):" in user
    assert "print(soma(1, 2))" in user


def test_build_messages_defaults_language_label_when_missing():
    user = completions.build_messages(prefix="x", suffix="y", path="f", language=None)[1]["content"]
    assert "linguagem: texto" in user


def test_clean_completion_strips_code_fences():
    out = completions.clean_completion(
        "```python\n    return a + b\n```", prefix="def f(a, b):\n", suffix=""
    )
    assert out == "    return a + b"


def test_clean_completion_drops_repetition_of_prefix_tail():
    # O modelo "recomeçou" a linha atual em vez de continuá-la.
    out = completions.clean_completion(
        "    return a + b", prefix="def f(a, b):\n    return ", suffix=""
    )
    assert out == "a + b"


def test_clean_completion_drops_repetition_of_suffix_head():
    out = completions.clean_completion(
        "value = 1\n    return value", prefix="def f():\n    ", suffix="    return value\n"
    )
    assert out == "value = 1\n"


def test_clean_completion_empty_when_only_whitespace_left():
    assert completions.clean_completion("   \n  ", prefix="", suffix="") == ""
    assert completions.clean_completion("", prefix="a", suffix="b") == ""


def test_extract_completion_reads_router_payload_shape():
    payload = {"choices": [{"message": {"content": "```\n  x = 1\n```"}}]}
    assert completions.extract_completion(payload, prefix="", suffix="") == "  x = 1"


def test_extract_completion_tolerates_missing_choices():
    assert completions.extract_completion({}, prefix="", suffix="") == ""
