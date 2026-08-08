"""PathGuard: Gerenciador de Segurança e Allowlist Dinâmica de Caminhos do Sistema Operacional."""

from __future__ import annotations

from pathlib import Path

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


class PathEscapeError(ValueError):
    def __init__(self, requested: str) -> None:
        super().__init__(f"Caminho não autorizado ou fora das workspaces permitidas: {requested!r}")


class PathGuard:
    """Registrador e validador de raízes de workspace autorizadas no sistema operacional."""

    def __init__(self) -> None:
        self._allowed_roots: set[Path] = set()

    def allow(self, target: Path | str) -> Path:
        """Adiciona um caminho à allowlist de diretórios autorizados."""
        resolved = Path(target).resolve()
        if not resolved.exists():
            raise ValueError(f"Caminho não existe no sistema de arquivos: {target}")
        if not resolved.is_dir():
            raise ValueError(f"O caminho especificado não é um diretório: {target}")
        
        self._allowed_roots.add(resolved)
        log.info("path_guard.allowed", path=str(resolved))
        return resolved

    def is_allowed(self, target: Path | str) -> bool:
        """Verifica se um caminho está dentro de alguma das raízes autorizadas."""
        try:
            resolved = Path(target).resolve()
        except Exception:
            return False

        return any(
            resolved == root or root in resolved.parents 
            for root in self._allowed_roots
        )

    def validate(self, target: Path | str) -> Path:
        """Valida e retorna o caminho resolvido ou levanta exceção se não autorizado."""
        resolved = Path(target).resolve()
        if not self.is_allowed(resolved):
            raise PathEscapeError(str(target))
        return resolved

    def list_allowed(self) -> list[str]:
        return [str(p) for p in sorted(self._allowed_roots)]


# Singleton global de proteção de caminhos
default_path_guard = PathGuard()
