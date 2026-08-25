"""Compressão de contexto.

A regra que atravessa todos estes testes: nunca comprimir o que está em jogo
agora. A última rodada de mensagens, a tarefa original e os diffs vão íntegros;
o que se comprime é o que já cumpriu seu papel.
"""

from __future__ import annotations

from novaai_studio.optimizer.compressor import ContextCompressor, truncate_output
from novaai_studio.optimizer.tokens import count_text


def _historico(n: int) -> list[dict]:
    """Histórico com n rodadas de assistente + ferramenta."""
    mensagens: list[dict] = [{"role": "user", "content": "Corrija o bug no adaptador."}]
    for i in range(n):
        mensagens.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": f"c{i}", "function": {"name": "read_file", "arguments": "{}"}}
                ],
            }
        )
        mensagens.append(
            {
                "role": "tool",
                "tool_call_id": f"c{i}",
                "name": "run_command",
                "content": "\n".join(f"linha {j} da rodada {i}" for j in range(400)),
            }
        )
    return mensagens


# ── Truncamento ─────────────────────────────────────────────────────────────


def test_short_output_is_untouched():
    texto = "\n".join(f"linha {i}" for i in range(10))
    assert truncate_output(texto) == texto


def test_truncation_keeps_head_and_tail():
    texto = "\n".join(f"linha {i}" for i in range(400))
    resumo = truncate_output(texto)

    assert "linha 0" in resumo
    assert "linha 399" in resumo
    assert count_text(resumo) < count_text(texto)


def test_truncation_preserves_error_lines():
    # Cortar só o início jogaria fora justamente o que interessa numa saída de
    # teste: as falhas.
    linhas = [f"ok {i}" for i in range(400)]
    linhas[200] = "FAILED tests/test_router.py::test_fallback - AssertionError"
    resumo = truncate_output("\n".join(linhas))

    assert "test_fallback" in resumo


# ── Pipeline ────────────────────────────────────────────────────────────────


async def test_short_history_is_not_compressed():
    mensagens = [{"role": "user", "content": "oi"}]
    resultado = await ContextCompressor().compress(mensagens)

    assert resultado.tokens_saved == 0
    assert resultado.messages == mensagens


async def test_disabled_compressor_is_a_passthrough():
    mensagens = _historico(10)
    resultado = await ContextCompressor(enabled=False).compress(mensagens)

    assert resultado.messages == mensagens
    assert resultado.tokens_saved == 0


async def test_old_tool_output_is_truncated():
    resultado = await ContextCompressor().compress(_historico(10))

    assert resultado.tokens_saved > 0
    assert resultado.savings.get("tool_truncation", 0) > 0
    assert resultado.tokens_after < resultado.tokens_before


async def test_recent_messages_are_never_touched():
    mensagens = _historico(10)
    original_finais = [dict(m) for m in mensagens[-4:]]

    resultado = await ContextCompressor(protected_recent=8).compress(mensagens)

    # As últimas mensagens são o que o modelo precisa íntegro para agir agora.
    assert resultado.messages[-4:] == original_finais


async def test_the_task_message_survives_pruning():
    mensagens = _historico(40)
    resultado = await ContextCompressor(prune_threshold=100).compress(mensagens)

    # Perder a primeira mensagem faria o agente esquecer o que estava fazendo.
    assert resultado.messages[0]["content"] == "Corrija o bug no adaptador."


async def test_pruning_condenses_the_middle_and_reports_it():
    mensagens = _historico(40)
    resultado = await ContextCompressor(prune_threshold=100).compress(mensagens)

    assert resultado.savings.get("history_pruning", 0) > 0
    assert len(resultado.messages) < len(mensagens)
    assert any(
        "Resumo dos passos anteriores" in str(m.get("content", ""))
        for m in resultado.messages
    )


async def test_repeated_file_reads_are_deduplicated():
    conteudo = "\n".join(f"def funcao_{i}(): pass" for i in range(200))
    mensagens: list[dict] = [{"role": "user", "content": "tarefa"}]
    for i in range(6):
        mensagens.append({"role": "assistant", "content": f"lendo (rodada {i})"})
        mensagens.append(
            {"role": "tool", "tool_call_id": f"c{i}", "name": "read_file", "content": conteudo}
        )
    mensagens.extend({"role": "assistant", "content": f"pensando {i}"} for i in range(8))

    resultado = await ContextCompressor().compress(mensagens)

    assert resultado.savings.get("file_dedup", 0) > 0
    # A cópia mais recente é a que fica; as antigas viram um marcador.
    leituras = [
        m for m in resultado.messages if m.get("name") == "read_file"
    ]
    completas = [m for m in leituras if "def funcao_0" in str(m.get("content", ""))]
    assert len(completas) == 1


async def test_different_versions_of_a_file_are_not_collapsed():
    # Duas leituras do mesmo arquivo com conteúdos diferentes (houve edição
    # entre elas) não são duplicata: colapsá-las apagaria a versão atual.
    antes = "\n".join(f"linha {i}" for i in range(200))
    depois = antes.replace("linha 5", "linha 5 EDITADA")

    mensagens: list[dict] = [{"role": "user", "content": "tarefa"}]
    mensagens.append({"role": "tool", "tool_call_id": "a", "name": "read_file", "content": antes})
    mensagens.append({"role": "tool", "tool_call_id": "b", "name": "read_file", "content": depois})
    mensagens.extend({"role": "assistant", "content": f"passo {i}"} for i in range(10))

    resultado = await ContextCompressor().compress(mensagens)

    conteudos = [
        str(m.get("content", ""))
        for m in resultado.messages
        if m.get("name") == "read_file"
    ]
    assert any("EDITADA" in c for c in conteudos)


async def test_summarizer_is_used_when_provided():
    async def resumir(_texto: str) -> str:
        return "o agente leu arquivos e rodou testes"

    resultado = await ContextCompressor(prune_threshold=100, summarizer=resumir).compress(
        _historico(40)
    )

    assert any(
        "o agente leu arquivos e rodou testes" in str(m.get("content", ""))
        for m in resultado.messages
    )


async def test_failing_summarizer_falls_back_instead_of_raising():
    async def quebrado(_texto: str) -> str:
        raise RuntimeError("modelo fora do ar")

    resultado = await ContextCompressor(prune_threshold=100, summarizer=quebrado).compress(
        _historico(40)
    )

    assert resultado.messages, "a compressão não pode derrubar o request"
    assert resultado.savings.get("history_pruning", 0) > 0
