"""Schemas da fachada OpenAI-compatible.

`extra="allow"` é proposital: clientes como Cline e Continue mandam campos que
não estão no core da API da OpenAI, e recusá-los quebraria a compatibilidade que
é o ponto do gateway. O que não for reconhecido segue para o litellm, que
descarta o que o provedor não aceita (`litellm.drop_params`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    stop: str | list[str] | None = None
    n: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    user: str | None = None

    def to_params(self) -> dict[str, Any]:
        """Parâmetros para o engine, sem `model` (quem resolve a rota é a policy)."""
        data = self.model_dump(exclude_none=True)
        data.pop("model", None)
        return data


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[str]
    user: str | None = None

    def inputs(self) -> list[str]:
        return [self.input] if isinstance(self.input, str) else list(self.input)


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "eltanix"
    # Campos fora do contrato da OpenAI; clientes bem comportados ignoram.
    context_window: int | None = None
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]
