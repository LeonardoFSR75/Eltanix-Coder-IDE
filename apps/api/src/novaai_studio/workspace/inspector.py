"""Project Inspector Engine: Inspeção automática de stack, linguagem, framework e containers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class ProjectSignature:
    name: str
    path: str
    primary_language: str = "unknown"
    frameworks: list[str] = field(default_factory=list)
    build_system: str = "unknown"
    has_docker: bool = False
    has_git: bool = False
    has_ci_cd: bool = False
    file_count_estimate: int = 0
    executive_summary: str = ""


class ProjectInspector:
    """Inspeciona assinaturas do diretório em <500ms e gera um resumo executivo."""

    def inspect(self, root: Path) -> ProjectSignature:
        resolved = root.resolve()
        name = resolved.name
        frameworks: list[str] = []
        primary_lang = "unknown"
        build_sys = "unknown"

        # 1. Checa Git
        has_git = (resolved / ".git").exists()

        # 2. Checa Docker
        has_docker = (resolved / "docker-compose.yml").exists() or (
            resolved / "Dockerfile"
        ).exists()

        # 3. Checa CI/CD
        has_ci_cd = (resolved / ".github" / "workflows").exists() or (
            resolved / ".gitlab-ci.yml"
        ).exists()

        # 4. Checagem Node.js / TypeScript / React / Next.js
        pkg_json = resolved / "package.json"
        if pkg_json.exists():
            primary_lang = "TypeScript/JavaScript"
            build_sys = "npm/pnpm/yarn"
            try:
                content = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {**content.get("dependencies", {}), **content.get("devDependencies", {})}
                if "next" in deps:
                    frameworks.append("Next.js")
                if "react" in deps:
                    frameworks.append("React")
                if "vue" in deps:
                    frameworks.append("Vue.js")
                if "express" in deps:
                    frameworks.append("Express")
                if "typescript" in deps:
                    primary_lang = "TypeScript"
            except Exception:
                pass

        # 5. Checagem Python
        pyproject = resolved / "pyproject.toml"
        reqs = resolved / "requirements.txt"
        if pyproject.exists() or reqs.exists() or list(resolved.glob("*.py")):
            if primary_lang == "unknown":
                primary_lang = "Python"
                build_sys = "uv/pip/poetry"

            if pyproject.exists():
                try:
                    txt = pyproject.read_text(encoding="utf-8")
                    if "fastapi" in txt.lower():
                        frameworks.append("FastAPI")
                    if "django" in txt.lower():
                        frameworks.append("Django")
                except Exception:
                    pass

        # 6. Checagem Java / Maven / Gradle
        if (resolved / "pom.xml").exists():
            primary_lang = "Java"
            build_sys = "Maven"
            frameworks.append("Spring Boot")
        elif (resolved / "build.gradle").exists():
            primary_lang = "Java/Kotlin"
            build_sys = "Gradle"

        # 7. Resumo Executivo
        summary_parts = [f"Projeto '{name}' em {primary_lang}."]
        if frameworks:
            summary_parts.append(f"Frameworks: {', '.join(frameworks)}.")
        if has_docker:
            summary_parts.append("Possui suporte a Docker/Containers.")
        if has_git:
            summary_parts.append("Repositório Git ativo.")

        return ProjectSignature(
            name=name,
            path=str(resolved),
            primary_language=primary_lang,
            frameworks=frameworks,
            build_system=build_sys,
            has_docker=has_docker,
            has_git=has_git,
            has_ci_cd=has_ci_cd,
            executive_summary=" ".join(summary_parts),
        )
