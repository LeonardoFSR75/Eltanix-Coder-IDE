"""Testes unitários da extração e classificação de PDFs via pdf-inspector e fallback."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from pypdf import PdfWriter

from eltanix.documents.service import _extract_pages, _extract_pdf


def _create_synthetic_pdf(text: str | None = None) -> bytes:
    """Cria um PDF sintético em memória para testes."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_extract_pdf_detects_scanned_without_text():
    """PDF em branco ou puramente imagem deve ser detectado e rejeitado com mensagem clara."""
    data = _create_synthetic_pdf()
    with pytest.raises(ValueError, match="digitalizado/escaneado"):
        _extract_pdf(data)


def test_extract_pdf_with_pdf_inspector(monkeypatch):
    """Testa extração com sucesso via pdf_inspector."""
    fake_proc = MagicMock()
    fake_proc.pdf_type = "text_based"
    fake_proc.page_count = 2
    fake_proc.pages_needing_ocr = []
    fake_proc.title = "Documento de Teste"
    fake_proc.markdown = "# Página 1\n\nConteúdo"

    fake_page_1 = MagicMock(markdown="# Página 1\n\nTexto página 1")
    fake_page_2 = MagicMock(markdown="## Página 2\n\nTabela | Coluna\n---|---\n1 | 2")
    fake_pages_res = MagicMock(pages=[fake_page_1, fake_page_2])

    fake_module = MagicMock()
    fake_module.process_pdf_bytes.return_value = fake_proc
    fake_module.extract_pages_markdown_bytes.return_value = fake_pages_res

    monkeypatch.setattr("pdf_inspector.process_pdf_bytes", fake_module.process_pdf_bytes)
    monkeypatch.setattr(
        "pdf_inspector.extract_pages_markdown_bytes",
        fake_module.extract_pages_markdown_bytes,
    )

    data = _create_synthetic_pdf()
    result = _extract_pdf(data)

    assert result.engine == "pdf_inspector"
    assert result.pdf_type == "text_based"
    assert result.page_count == 2
    assert len(result.pages) == 2
    assert "Página 1" in result.pages[0]
    assert "Tabela" in result.pages[1]


def test_extract_pdf_fallback_to_pypdf(monkeypatch):
    """Se pdf_inspector falhar inesperadamente, o fallback para pypdf deve funcionar."""

    def mock_fail(*args, **kwargs):
        raise RuntimeError("Falha interna de extensão Rust")

    monkeypatch.setattr("pdf_inspector.process_pdf_bytes", mock_fail)

    data = _create_synthetic_pdf()
    result = _extract_pdf(data)

    assert result.engine == "pypdf"
    assert result.pdf_type == "unknown"
    assert result.page_count == 1
    assert isinstance(result.pages, list)


def test_extract_pages_backward_compatibility(monkeypatch):
    """Garante que a função legada _extract_pages continua retornando list[str]."""
    fake_proc = MagicMock()
    fake_proc.pdf_type = "text_based"
    fake_proc.page_count = 1
    fake_proc.pages_needing_ocr = []
    fake_proc.title = None
    fake_proc.markdown = "Texto simples"

    fake_module = MagicMock()
    fake_module.process_pdf_bytes.return_value = fake_proc
    fake_module.extract_pages_markdown_bytes.return_value = MagicMock(
        pages=[MagicMock(markdown="Texto simples")]
    )

    monkeypatch.setattr("pdf_inspector.process_pdf_bytes", fake_module.process_pdf_bytes)
    monkeypatch.setattr(
        "pdf_inspector.extract_pages_markdown_bytes",
        fake_module.extract_pages_markdown_bytes,
    )

    data = _create_synthetic_pdf()
    pages = _extract_pages(data)
    assert pages == ["Texto simples"]
