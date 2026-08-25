"""Regras de contexto por glob (Fase 4 do upgrade do agente, estilo `.cursor/rules`):
instruções extras injetadas no system prompt só quando o foco da sessão
(`focus_files`/`focus_folder`) bate num glob.

Glob simples via `fnmatch` sobre o caminho relativo ao workspace — mesmo espírito
"sem DSL" de `EditPathRule.path_glob` em `agent/approval_policy.py`. Avaliado uma
única vez na criação da sessão (`agent/runner.py`), pelo mesmo motivo que
`custom_instructions`/`routed_skills_prompt` também são: manter o prefixo do system
prompt estável entre turnos preserva o prompt caching (ver docstring de
`SYSTEM_PROMPT` em `agent/prompts.py`). Regras que só baterem em arquivos tocados
depois da criação da sessão não retroagem — trade-off aceito, mesmo espírito.
"""

from __future__ import annotations

import fnmatch

from pydantic import BaseModel, Field

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


class ContextRule(BaseModel):
    glob: str
    instructions: str


class ContextRulesConfig(BaseModel):
    version: int = 1
    rules: list[ContextRule] = Field(default_factory=list)


def _matches(rule: ContextRule, path: str) -> bool:
    normalizado = path.replace("\\", "/")
    return fnmatch.fnmatch(normalizado, rule.glob)


def match_context_rules(
    config: ContextRulesConfig,
    *,
    focus_files: list[str] | None,
    focus_folder: str | None,
) -> list[ContextRule]:
    """Regras cujo glob bate em pelo menos um `focus_files` ou no `focus_folder` —
    na ordem declarada no YAML, sem deduplicar (cada regra é sua própria seção do
    prompt). Glob malformado numa regra específica não derruba as outras: conta
    como "essa regra não casou", mesma filosofia fail-closed de `evaluate_policy`."""
    alvos = list(focus_files or [])
    if focus_folder:
        alvos.append(focus_folder)
    if not alvos:
        return []

    casadas: list[ContextRule] = []
    for rule in config.rules:
        try:
            if any(_matches(rule, alvo) for alvo in alvos):
                casadas.append(rule)
        except Exception as exc:
            log.warning("agent.context_rules.match_failed", glob=rule.glob, error=str(exc)[:200])
            continue
    return casadas


def build_context_rules_prompt(rules: list[ContextRule]) -> str | None:
    """Seção opcional do system prompt — mesmo mecanismo aditivo de
    `custom_instructions`/`routed_skills_prompt` em `agent/graph.py::build_graph()`.
    `None` quando nenhuma regra casou (degrada silenciosamente)."""
    if not rules:
        return None
    secoes = "\n\n".join(f"### Regra para `{r.glob}`\n\n{r.instructions}" for r in rules)
    return "## Regras de contexto ativas para os arquivos/pastas em foco\n\n" + secoes
