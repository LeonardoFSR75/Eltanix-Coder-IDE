"""Integração com Langfuse para observabilidade de agentes e chamadas de LLM.

Seguindo as invariantes de arquitetura do projeto:
- Serviço opcional: falhas de importação, chaves ausentes ou problemas de rede
  NUNCA propagam erro nem interrompem a execução da API ou do agente.
"""

from __future__ import annotations

from typing import Any

from sicoobito.config import Settings, get_settings
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


def is_langfuse_configured(settings: Settings | None = None) -> bool:
    """Verifica se o Langfuse está habilitado e com chaves configuradas."""
    cfg = settings or get_settings()
    if not cfg.langfuse_enabled:
        return False
    return bool(cfg.langfuse_public_key.strip() and cfg.langfuse_secret_key.strip())


def _get_callback_class() -> Any:
    """Importa dinamicamente a classe CallbackHandler da biblioteca langfuse."""
    try:
        from langfuse.callback import CallbackHandler

        return CallbackHandler
    except ImportError:
        try:
            from langfuse.langchain import CallbackHandler  # type: ignore[no-redef]

            return CallbackHandler
        except ImportError:
            from langfuse import CallbackHandler  # type: ignore[no-redef]

            return CallbackHandler


def get_langfuse_callback(
    session_id: str | None = None,
    trace_name: str = "sicoobito-agent",
    tags: list[str] | None = None,
    settings: Settings | None = None,
) -> Any | None:
    """Retorna uma instância de `CallbackHandler` para ser usada no LangGraph/LangChain.

    Devolve `None` se o Langfuse não estiver habilitado, faltarem credenciais ou
    houver erro na inicialização (degradação suave).
    """
    if not is_langfuse_configured(settings):
        return None

    cfg = settings or get_settings()

    try:
        cls = _get_callback_class()
        handler = cls(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=cfg.langfuse_host,
            session_id=session_id,
            trace_name=trace_name,
            tags=tags or ["sicoobito"],
        )
        return handler
    except Exception as exc:
        log.warning("langfuse.callback_init_failed", error=str(exc)[:200])
        return None


def flush_langfuse() -> None:
    """Força o envio em background de eventos pendentes do Langfuse."""
    try:
        import langfuse

        if hasattr(langfuse, "flush"):
            langfuse.flush()
    except Exception as exc:
        log.debug("langfuse.flush_failed", error=str(exc)[:200])
