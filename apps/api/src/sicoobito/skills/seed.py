"""Seed de habilidades (agent-skills do Addy Osmani).

Importa as 24 habilidades de engenharia de software do repositório
`.agents/agent-skills` para a tabela `skill` no banco de dados.
"""

from __future__ import annotations

import re
from pathlib import Path

from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger
from sicoobito.skills import store

log = get_logger(__name__)


def parse_skill_markdown(filepath: Path) -> dict[str, str] | None:
    """Lê SKILL.md e extrai name, description do frontmatter e o texto como system_prompt."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as exc:
        log.warning("skills.seed.read_failed", path=str(filepath), error=str(exc))
        return None

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        return None

    frontmatter_text, body_text = frontmatter_match.groups()

    name = ""
    description = ""
    for line in frontmatter_text.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip()

    if not name:
        name = filepath.parent.name

    return {
        "name": name,
        "description": description or f"Habilidade {name}",
        "category": "engineering",
        "system_prompt": body_text.strip(),
        "parameters_json": "{}",
    }


async def seed_agent_skills(skills_dir: Path) -> int:
    """Carrega e sincroniza todas as skills em `skills_dir` (recursivo) para a tabela `skill`."""
    if not skills_dir.exists() or not skills_dir.is_dir():  # noqa: ASYNC240
        log.warning("skills.seed.dir_not_found", path=str(skills_dir))
        return 0

    count = 0
    async with session_scope() as session:
        existing_skills = await store.list_skills(session)
        existing_names = {s.name for s in existing_skills}

        for skill_md in sorted(skills_dir.rglob("SKILL.md")):  # noqa: ASYNC240
            parsed = parse_skill_markdown(skill_md)
            if not parsed:
                continue

            if parsed["name"] not in existing_names:
                await store.create_skill(
                    session,
                    name=parsed["name"],
                    description=parsed["description"],
                    category=parsed["category"],
                    system_prompt=parsed["system_prompt"],
                    parameters_json=parsed["parameters_json"],
                )
                existing_names.add(parsed["name"])
                count += 1
                log.info("skills.seed.imported", name=parsed["name"])

    return count
