"""Testes unitários da extração multi-formato de documentos via AnyDoc."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from novaai_studio.documents.service import (
    _detect_format_from_filename_or_content_type,
    _extract_document_content,
)


def _create_synthetic_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_detect_format_mapping():
    assert _detect_format_from_filename_or_content_type("doc.pdf", None) == "pdf"
    assert _detect_format_from_filename_or_content_type("relatorio.docx", None) == "docx"
    assert _detect_format_from_filename_or_content_type("planilha.xlsx", None) == "xlsx"
    assert _detect_format_from_filename_or_content_type("dados.csv", None) == "csv"
    assert _detect_format_from_filename_or_content_type("apresentacao.pptx", None) == "pptx"
    assert _detect_format_from_filename_or_content_type("livro.epub", None) == "epub"
    assert _detect_format_from_filename_or_content_type("texto.odt", None) == "odt"
    assert _detect_format_from_filename_or_content_type("readme.md", None) == "md"
    assert _detect_format_from_filename_or_content_type("notes.txt", None) == "txt"
    assert _detect_format_from_filename_or_content_type("arquivo", "application/pdf") == "pdf"
    assert (
        _detect_format_from_filename_or_content_type(
            "arquivo",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        == "docx"
    )


def test_extract_csv_to_markdown_table():
    csv_bytes = b"id,nome,cargo\n1,Leonardo,Engenheiro\n2,Alice,Arquiteta\n"
    res = _extract_document_content(csv_bytes, filename="equipe.csv", content_type="text/csv")
    assert res.engine == "anydoc"
    assert res.doc_type == "csv"
    assert len(res.pages) == 1
    markdown = res.pages[0]
    assert "| id | nome | cargo |" in markdown
    assert "Leonardo" in markdown
    assert "Arquiteta" in markdown


def test_extract_rtf_to_markdown():
    rtf_bytes = br"{\rtf1\ansi Especificacao de {\b Arquitetura} do Sistema}"
    res = _extract_document_content(rtf_bytes, filename="arch.rtf", content_type="application/rtf")
    assert res.engine == "anydoc"
    assert res.doc_type == "rtf"
    assert len(res.pages) == 1
    markdown = res.pages[0]
    assert "Especificacao de" in markdown
    assert "**Arquitetura**" in markdown


def test_extract_markdown_and_plaintext():
    md_bytes = b"# Titulo do Documento\n\nEste e um paragrafo explicativo."
    res = _extract_document_content(md_bytes, filename="guia.md", content_type="text/markdown")
    assert res.engine == "text"
    assert res.doc_type == "md"
    assert "# Titulo do Documento" in res.pages[0]

    txt_bytes = b"Linha 1\nLinha 2"
    res_txt = _extract_document_content(txt_bytes, filename="log.txt", content_type="text/plain")
    assert res_txt.engine == "text"
    assert res_txt.doc_type == "txt"
    assert "Linha 1\nLinha 2" in res_txt.pages[0]


def test_extract_pdf_delegates_properly():
    pdf_bytes = _create_synthetic_pdf()
    with pytest.raises(ValueError, match="digitalizado/escaneado"):
        _extract_document_content(
            pdf_bytes, filename="documento.pdf", content_type="application/pdf"
        )


def test_extract_empty_file_raises_error():
    with pytest.raises(ValueError, match=r"Falha ao processar|Nenhum texto"):
        _extract_document_content(
            b"",
            filename="vazio.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
