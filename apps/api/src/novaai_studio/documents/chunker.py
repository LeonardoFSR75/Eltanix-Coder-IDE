"""Fatiamento de texto em prosa (documentos, notas) — consciente de parágrafos.

Separado do chunker de código (`context/chunker.py`): aquele se apoia em
símbolos via tree-sitter, este não tem estrutura sintática nenhuma — só
parágrafos e, quando um parágrafo sozinho estoura o limite, sentenças.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from novaai_studio.optimizer.tokens import count_text

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class TextChunk:
    content: str
    chunk_index: int
    token_count: int
    page_number: int | None = None


def _split_paragraph(paragraph: str, max_tokens: int) -> list[str]:
    """Um parágrafo maior que o limite vira várias sentenças agrupadas."""
    if count_text(paragraph) <= max_tokens:
        return [paragraph]

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in _SENTENCE_SPLIT.split(paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        tokens = count_text(sentence)
        if current and current_tokens + tokens > max_tokens:
            pieces.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += tokens
    if current:
        pieces.append(" ".join(current))
    return pieces or [paragraph]


def chunk_text(
    text: str,
    *,
    chunk_tokens: int = 512,
    overlap_tokens: int = 64,
    page_number: int | None = None,
) -> list[TextChunk]:
    """Fatia texto em janelas de ~`chunk_tokens`, com sobreposição de `overlap_tokens`.

    A sobreposição evita que uma frase relevante fique cortada exatamente na
    fronteira entre dois chunks, deixando cada metade sem contexto suficiente
    para embeddar bem.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs: list[str] = []
    for raw in _PARAGRAPH_SPLIT.split(text):
        raw = raw.strip()
        if raw:
            paragraphs.extend(_split_paragraph(raw, chunk_tokens))

    chunks: list[TextChunk] = []
    current: list[str] = []
    current_tokens = 0
    index = 0

    def flush() -> None:
        nonlocal index
        if not current:
            return
        content = "\n\n".join(current)
        chunks.append(
            TextChunk(
                content=content,
                chunk_index=index,
                token_count=count_text(content),
                page_number=page_number,
            )
        )
        index += 1

    for paragraph in paragraphs:
        tokens = count_text(paragraph)
        if current and current_tokens + tokens > chunk_tokens:
            flush()
            # Carrega os últimos parágrafos do chunk que acabou de fechar, até
            # somar ~overlap_tokens, para o próximo não começar no vácuo.
            overlap: list[str] = []
            overlap_count = 0
            for previous in reversed(current):
                previous_tokens = count_text(previous)
                if overlap_count and overlap_count + previous_tokens > overlap_tokens:
                    break
                overlap.insert(0, previous)
                overlap_count += previous_tokens
            current, current_tokens = overlap, overlap_count

        current.append(paragraph)
        current_tokens += tokens

    flush()
    return chunks
