"""Testes unitários para o sanitizador PIIRedactor."""

from novaai_studio.security.pii_redactor import PIIRedactor


def test_pii_redactor_cpf():
    text = "O usuário com CPF 123.456.789-00 solicitou um reembolso."
    res = PIIRedactor.redact(text)
    assert "[REDACTED_CPF]" in res.sanitized_text
    assert "123.456.789-00" not in res.sanitized_text
    assert res.redacted_count == 1


def test_pii_redactor_email():
    text = "Enviar relatórios para leandro.admin@novaai-studio.com.br imediatamente."
    res = PIIRedactor.redact(text)
    assert "[REDACTED_EMAIL]" in res.sanitized_text
    assert "leandro.admin@novaai-studio.com.br" not in res.sanitized_text
    assert res.redacted_count == 1


def test_pii_redactor_api_key():
    text = "Utilizando a chave sk-proj-1234567890abcdef1234567890 para autenticar."
    res = PIIRedactor.redact(text)
    assert "[REDACTED_API_KEY]" in res.sanitized_text
    assert "sk-proj-1234567890abcdef1234567890" not in res.sanitized_text
    assert res.redacted_count == 1


def test_pii_redactor_clean_text():
    text = "Este é um texto limpo sem nenhuma informação sensível."
    res = PIIRedactor.redact(text)
    assert res.sanitized_text == text
    assert res.redacted_count == 0
