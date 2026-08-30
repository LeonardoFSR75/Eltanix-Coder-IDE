"""Parte pura da predição do próximo edit (`context/next_edit.py`) — janela,
numeração de linha, montagem do prompt, parse fail-closed e validação do
intervalo contra o arquivo real. A chamada de LLM fica na rota."""

from __future__ import annotations

from eltanix.context import next_edit

FILE = "def soma(a, b):\n    return a + b\n\n\nprint(soma(1, 2))\n"


def test_select_window_keeps_small_files_intact():
    assert next_edit.select_window(FILE, 2) == (FILE, 1)


def test_select_window_centers_on_cursor_for_big_files():
    big = "".join(f"linha {i}\n" for i in range(1, 4001))  # ~ bem acima do teto
    window, base = next_edit.select_window(big, 2000, max_chars=1000)
    assert base >= 1
    assert f"linha {2000}" in window
    assert len(window) <= 1200  # teto + folga de uma linha


def test_number_lines_prefixes_from_start():
    numbered = next_edit.number_lines("a\nb\nc", start=10)
    assert numbered.splitlines() == ["10| a", "11| b", "12| c"]


def test_build_messages_carries_cursor_recent_edits_and_file():
    msgs = next_edit.build_messages(
        numbered_file="1| x = 1",
        cursor_line=1,
        recent_edits=[{"path": "a.py", "diff": "- x = 0\n+ x = 1"}],
    )
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert "CURSOR na linha 1" in user
    assert "a.py" in user and "+ x = 1" in user
    assert "1| x = 1" in user


def test_build_messages_without_history_says_so():
    user = next_edit.build_messages(numbered_file="1| x", cursor_line=1, recent_edits=[])[1][
        "content"
    ]
    assert "sem histórico de edição recente" in user


def test_parse_prediction_reads_valid_object():
    pred = next_edit.parse_prediction(
        '{"found": true, "start_line": 2, "end_line": 2, "replacement": "    return a - b"}'
    )
    assert pred == {"start_line": 2, "end_line": 2, "replacement": "    return a - b"}


def test_parse_prediction_tolerates_code_fence():
    pred = next_edit.parse_prediction(
        '```json\n{"found": true, "start_line": 1, "end_line": 1, "replacement": "x"}\n```'
    )
    assert pred["start_line"] == 1


def test_parse_prediction_none_when_not_found():
    assert next_edit.parse_prediction('{"found": false}') is None


def test_parse_prediction_none_on_garbage_or_missing_keys():
    assert next_edit.parse_prediction("desculpe, não sei") is None
    assert next_edit.parse_prediction('{"found": true, "start_line": 1}') is None
    assert (
        next_edit.parse_prediction(
            '{"found": true, "start_line": 3, "end_line": 1, "replacement": "x"}'
        )
        is None
    )
    assert (
        next_edit.parse_prediction(
            '{"found": true, "start_line": 1, "end_line": 1, "replacement": 5}'
        )
        is None
    )


def test_validate_prediction_slices_old_text_from_the_real_file():
    edit = next_edit.validate_prediction(
        {"start_line": 2, "end_line": 2, "replacement": "    return a - b"},
        full_content=FILE,
        cursor_line=1,
    )
    assert edit is not None
    assert edit.old_text == "    return a + b\n"  # do arquivo, com a quebra
    assert edit.new_text == "    return a - b\n"  # quebra final normalizada
    assert edit.diff  # diff não-vazio
    assert edit.jump_lines == 1


def test_validate_prediction_rejects_out_of_bounds_range():
    assert (
        next_edit.validate_prediction(
            {"start_line": 40, "end_line": 99, "replacement": "x"},
            full_content=FILE,
            cursor_line=1,
        )
        is None
    )


def test_validate_prediction_rejects_noop():
    assert (
        next_edit.validate_prediction(
            {"start_line": 2, "end_line": 2, "replacement": "    return a + b"},
            full_content=FILE,
            cursor_line=1,
        )
        is None
    )


def test_predict_from_payload_reads_router_shape():
    payload = {
        "choices": [
            {
                "message": {
                    "content": '{"found": true, "start_line": 5, "end_line": 5, "replacement": "print(soma(3, 4))"}'
                }
            }
        ]
    }
    edit = next_edit.predict_from_payload(payload, full_content=FILE, cursor_line=1)
    assert edit is not None
    assert edit.start_line == 5
    assert "soma(3, 4)" in edit.new_text
    assert edit.jump_lines == 4


def test_predict_from_payload_none_on_empty_payload():
    assert next_edit.predict_from_payload({}, full_content=FILE, cursor_line=1) is None
