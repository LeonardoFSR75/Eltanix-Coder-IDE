"""Predição do próximo edit / "tab to jump" — Onda 1.2 (`docs/adr/0015-predicao-do-proximo-edit.md`).

Dado o histórico de edições recentes + o arquivo atual, prevê **um** trecho
(linhas X–Y do arquivo) e a substituição dele — quase sempre propagar a
mudança recém-feita para outro ponto. Toda a chamada passa pelo `RouterEngine`
(ADR 0001); este módulo monta o prompt e **valida** a resposta contra o
arquivo real antes de devolver.

Parte pura (`select_window`, `number_lines`, `build_messages`,
`parse_prediction`, `validate_prediction`) — o que `tests/test_next_edit.py`
exercita. A chamada de LLM fica na rota.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass

# Tetos (ADR 0015 §3). Arquivo grande é janelado em torno do cursor.
MAX_FILE_CHARS = 16000
MAX_RECENT_EDITS = 10
MAX_EDIT_DIFF_CHARS = 2000
MAX_TOKENS = 256

SYSTEM_PROMPT = """Você prevê a PRÓXIMA edição que um desenvolvedor fará, dado o que ele acabou \
de editar e o arquivo atual (com números de linha à esquerda). Quase sempre é propagar a \
mudança recém-feita para outro ponto: renomear onde mais o símbolo aparece, ajustar quem chama \
uma função cuja assinatura mudou, atualizar um teste, completar um par que ficou pela metade.

Responda SOMENTE com um objeto JSON, sem cercas de código:
- Se há uma próxima edição clara: {"found": true, "start_line": <int>, "end_line": <int>, \
"replacement": "<texto novo das linhas start_line..end_line, inclusive, SEM os números>"}
- Se não há nada óbvio a prever: {"found": false}

As linhas são 1-based e referenciam os números mostrados no arquivo. `replacement` substitui o \
bloco inteiro de start_line até end_line. Não invente uma edição fraca só para responder \
`found: true`."""

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\r?\n?|\r?\n?```\s*$")


@dataclass(slots=True)
class PredictedEdit:
    start_line: int
    end_line: int
    old_text: str
    new_text: str
    diff: str
    jump_lines: int


def select_window(
    content: str, cursor_line: int, *, max_chars: int = MAX_FILE_CHARS
) -> tuple[str, int]:
    """Se o arquivo cabe no teto, devolve `(content, 1)`. Senão, janela de
    linhas em torno do cursor — devolve `(janela, primeira_linha_1based)`."""
    if len(content) <= max_chars:
        return content, 1

    lines = content.splitlines()
    # ~metade das linhas do arquivo original que caberiam no teto, centradas no cursor.
    avg_len = max(1, len(content) // max(1, len(lines)))
    budget_lines = max(40, max_chars // avg_len)
    half = budget_lines // 2
    start = max(1, cursor_line - half)
    end = min(len(lines), start + budget_lines - 1)
    start = max(1, end - budget_lines + 1)
    return "\n".join(lines[start - 1 : end]), start


def number_lines(content: str, *, start: int = 1) -> str:
    """Prefixa cada linha com `<n>| ` (n 1-based a partir de `start`)."""
    return "\n".join(f"{i}| {line}" for i, line in enumerate(content.splitlines(), start=start))


def build_messages(
    *, numbered_file: str, cursor_line: int, recent_edits: list[dict[str, str]]
) -> list[dict[str, str]]:
    edits = recent_edits[:MAX_RECENT_EDITS]
    blocos = (
        "\n\n".join(
            f"[{e.get('path', '?')}]\n{(e.get('diff') or '')[:MAX_EDIT_DIFF_CHARS]}" for e in edits
        )
        or "(sem histórico de edição recente)"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"EDIÇÕES RECENTES (mais nova por último):\n{blocos}\n\n"
                f"CURSOR na linha {cursor_line}.\n\n"
                f"ARQUIVO ATUAL:\n{numbered_file}"
            ),
        },
    ]


def _strip_fence(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _FENCE_RE.sub("", text)
    return text


def parse_prediction(text: str) -> dict | None:
    """JSON `{found, start_line, end_line, replacement}` → dict cru, ou `None`
    (fail-closed: `found: false`, formato errado, chaves faltando)."""
    if not text:
        return None
    try:
        data = json.loads(_strip_fence(text).strip())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("found"):
        return None
    try:
        start = int(data["start_line"])
        end = int(data["end_line"])
    except (KeyError, TypeError, ValueError):
        return None
    replacement = data.get("replacement")
    if not isinstance(replacement, str) or start < 1 or end < start:
        return None
    return {"start_line": start, "end_line": end, "replacement": replacement}


def validate_prediction(pred: dict, *, full_content: str, cursor_line: int) -> PredictedEdit | None:
    """Confere o intervalo contra o arquivo real, monta o `old_text` a partir
    dele (não do que o modelo alegou), rejeita no-op e devolve o `PredictedEdit`
    com diff e `jump_lines`."""
    lines = full_content.splitlines(keepends=True)
    start, end = pred["start_line"], pred["end_line"]
    if end > len(lines):
        return None

    old_text = "".join(lines[start - 1 : end])
    new_text = pred["replacement"]
    # Normaliza a quebra final: o modelo quase nunca devolve o `\n` do fim do
    # bloco; se o trecho original termina em `\n`, casa.
    if old_text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    if new_text == old_text:
        return None

    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"linha {start}",
            tofile=f"linha {start} (previsto)",
            n=1,
        )
    )
    jump = min(abs(start - cursor_line), abs(end - cursor_line))
    return PredictedEdit(
        start_line=start,
        end_line=end,
        old_text=old_text,
        new_text=new_text,
        diff=diff,
        jump_lines=jump,
    )


def predict_from_payload(
    payload: dict, *, full_content: str, cursor_line: int
) -> PredictedEdit | None:
    """`parse_prediction` + `validate_prediction` direto no payload do router."""
    choice = (payload.get("choices") or [{}])[0]
    raw = (choice.get("message") or {}).get("content") or ""
    pred = parse_prediction(raw)
    if pred is None:
        return None
    return validate_prediction(pred, full_content=full_content, cursor_line=cursor_line)
