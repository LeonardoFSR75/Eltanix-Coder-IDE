"""Seed de habilidades (agent-skills do Addy Osmani + skills curadas do projeto).

Importa todas as habilidades encontradas recursivamente em `.agents/` (skills
curadas em `.agents/skills/` + o pacote vendorizado em `.agents/agent-skills/`)
para a tabela `skill` no banco de dados.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from novaai_studio.db.session import session_scope
from novaai_studio.logging_setup import get_logger
from novaai_studio.skills import store

if TYPE_CHECKING:
    from novaai_studio.router.engine import RouterEngine

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


async def seed_agent_skills(
    skills_dir: Path,
    *,
    engine: RouterEngine | None = None,
    embedding_profile: str = "embedding",
) -> int:
    """Carrega e sincroniza todas as skills em `skills_dir` (recursivo) para a tabela `skill`.

    Quando `engine` é passado, também calcula o embedding de `description` de
    cada skill nova (roteamento automático, Fase 1 do upgrade do agente) —
    best-effort: uma falha do provedor de embedding não impede o seed, a skill
    só fica sem embedding até um recálculo futuro (nunca entra no roteamento
    automático até lá, mas continua acessível via `list_skills`/`get_skill`).
    """
    if not skills_dir.exists() or not skills_dir.is_dir():  # noqa: ASYNC240
        log.warning("skills.seed.dir_not_found", path=str(skills_dir))
        return 0

    count = 0
    novas: list[tuple[str, str]] = []  # (skill_id, description) — embedado fora da transação
    async with session_scope() as session:
        existing_map = {s.name: s for s in existing_skills}

        for skill_md in sorted(skills_dir.rglob("SKILL.md")):  # noqa: ASYNC240
            parsed = parse_skill_markdown(skill_md)
            if not parsed:
                continue

            name = parsed["name"]
            if name not in existing_map:
                skill = await store.create_skill(
                    session,
                    name=name,
                    description=parsed["description"],
                    category=parsed["category"],
                    system_prompt=parsed["system_prompt"],
                    parameters_json=parsed["parameters_json"],
                )
                existing_map[name] = skill
                novas.append((str(skill.id), parsed["description"]))
                count += 1
                log.info("skills.seed.imported", name=name)
            else:
                existing = existing_map[name]
                if (
                    existing.system_prompt != parsed["system_prompt"]
                    or existing.description != parsed["description"]
                ):
                    await store.update_skill(
                        session,
                        existing.id,
                        name=name,
                        description=parsed["description"],
                        category=parsed["category"],
                        system_prompt=parsed["system_prompt"],
                        parameters_json=parsed["parameters_json"],
                    )
                    count += 1
                    log.info("skills.seed.updated", name=name)

    if engine is not None and novas:
        await _embed_new_skills(engine, embedding_profile, novas)

    return count


async def _embed_new_skills(
    engine: RouterEngine, embedding_profile: str, skills: list[tuple[str, str]]
) -> None:
    import uuid

    try:
        resultado = await engine.embed(
            requested_model=embedding_profile,
            inputs=[description for _, description in skills],
            source="skills.seed",
        )
    except Exception as exc:
        log.warning("skills.seed.embed_failed", error=str(exc)[:200], count=len(skills))
        return

    data = resultado.payload.get("data") or []
    async with session_scope() as session:
        for (skill_id, _), item in zip(skills, data, strict=False):
            vetor = item.get("embedding")
            if not vetor:
                continue
            await store.set_description_embedding(session, uuid.UUID(skill_id), vetor)
