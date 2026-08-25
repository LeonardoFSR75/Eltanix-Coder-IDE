"""Slash commands reais do agente.

Antes desta feature, `/explain /fix /test /refactor /docs` no rodapé de
`AgentChatInput.tsx` eram só um `<kbd>` de enfeite — o texto ia literal pro
agente, sem nenhuma expansão. Este módulo espelha o padrão do Antigravity CLI
(`.agents/agent-skills/docs/antigravity-setup.md`): cada comando reconhecido
ativa deterministicamente uma skill já seedada em `skill` (ver `skills/seed.py`)
e sugere um modo — sem precisar do roteamento por similaridade da Fase 1
(`AgentRunner._route_skills`), que é probabilístico e serve o caso geral, não
o comando explícito.

`skill_name` casa exatamente com o campo `name:` do frontmatter de cada
`SKILL.md` (ver `skills/seed.py::parse_skill_markdown`) — não o nome do
diretório, que às vezes diverge (ex: a skill do diretório
`.agents/agent-skills/agents/web-performance-auditor.md` não é um `SKILL.md`
e nunca é seedada; o comando `/webperf` mapeia para `performance-optimization`,
que é a skill real mais próxima em `.agents/agent-skills/skills/`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlashCommand:
    command: str
    skill_name: str | None
    suggested_mode: str | None
    description: str


SLASH_COMMANDS: dict[str, SlashCommand] = {
    "/spec": SlashCommand(
        "/spec",
        "spec-driven-development",
        "plan",
        "Escreve uma especificação estruturada antes de codar",
    ),
    "/planning": SlashCommand(
        "/planning",
        "planning-and-task-breakdown",
        "plan",
        "Quebra o trabalho em tarefas pequenas e verificáveis",
    ),
    "/build": SlashCommand(
        "/build",
        "incremental-implementation",
        "agent",
        "Implementa a próxima tarefa de forma incremental",
    ),
    "/test": SlashCommand(
        "/test",
        "test-driven-development",
        "orchestra",
        "Ciclo TDD: teste falha, implementa, teste passa",
    ),
    "/review": SlashCommand(
        "/review",
        "code-review-and-quality",
        "ask",
        "Revisão de código em cinco eixos",
    ),
    "/simplify": SlashCommand(
        "/simplify",
        "code-simplification",
        "edit",
        "Reduz complexidade sem mudar comportamento",
    ),
    "/ship": SlashCommand(
        "/ship",
        "shipping-and-launch",
        "agent",
        "Checklist de pré-lançamento",
    ),
    "/webperf": SlashCommand(
        "/webperf",
        "performance-optimization",
        "ask",
        "Audita performance e Core Web Vitals",
    ),
    "/fix": SlashCommand(
        "/fix",
        "debugging-and-error-recovery",
        "agent",
        "Investiga e corrige um bug",
    ),
    "/refactor": SlashCommand(
        "/refactor",
        "dev-code-refactoring",
        "edit",
        "Refatoração seguindo as convenções do projeto",
    ),
    "/docs": SlashCommand(
        "/docs",
        "documentation-and-adrs",
        "edit",
        "Documentação e ADRs",
    ),
    "/explain": SlashCommand(
        "/explain",
        None,
        "ask",
        "Explica código ou arquitetura sem alterar nada",
    ),
}


def resolve_slash_command(task: str) -> tuple[str, SlashCommand | None]:
    """Se `task` começa com um comando reconhecido, devolve o texto sem o
    prefixo do comando e o `SlashCommand` correspondente. Caso contrário
    (texto comum, ou `/algo` não cadastrado), devolve `task` inalterado e
    `None` — o texto nunca é descartado, só potencialmente reescrito."""
    stripped = task.lstrip()
    if not stripped.startswith("/"):
        return task, None

    primeira_palavra, _, resto = stripped.partition(" ")
    comando = SLASH_COMMANDS.get(primeira_palavra.lower())
    if comando is None:
        return task, None
    return resto.lstrip(), comando
