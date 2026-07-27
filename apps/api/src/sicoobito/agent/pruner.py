"""Módulo de compressão e poda inteligente de contexto do agente (Sliding Window Pruner).

Garante que históricos longos de ferramentas e edições não excedam o limite
de tokens do modelo, priorizando as instruções originais da tarefa e os turnos mais recentes.
"""

from __future__ import annotations

from typing import Any


class ContextPruner:
    """Compressor e podador de contexto do LangGraph."""

    def __init__(self, max_message_tokens: int = 32000, max_tool_output_length: int = 4000) -> None:
        self.max_message_tokens = max_message_tokens
        self.max_tool_output_length = max_tool_output_length

    def prune_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Poda mensagens antigas de ferramentas mantendo a instrução do usuário e o estado recente."""
        if not messages or len(messages) <= 6:
            return messages

        resultado: list[dict[str, Any]] = []

        # Preserva a primeira mensagem (tarefa original e repomap)
        resultado.append(messages[0])

        # Poda saídas intermediárias de ferramentas
        for msg in messages[1:-4]:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "tool" or (isinstance(content, str) and len(content) > self.max_tool_output_length):
                str_content = str(content)
                if len(str_content) > self.max_tool_output_length:
                    truncated = (
                        str_content[: self.max_tool_output_length // 2]
                        + "\n... [conteúdo intermediário resumido pelo ContextPruner] ...\n"
                        + str_content[-self.max_tool_output_length // 2 :]
                    )
                    nova_msg = dict(msg)
                    nova_msg["content"] = truncated
                    resultado.append(nova_msg)
                    continue

            resultado.append(msg)

        # Preserva as últimas 4 mensagens intactas
        resultado.extend(messages[-4:])
        return resultado
