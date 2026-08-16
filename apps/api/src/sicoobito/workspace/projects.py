"""Descoberta, resolução e gestão centralizada de projetos.

O IDE abre projetos diferentes ao longo do dia, então `PROJECTS_ROOT` aponta
para a pasta que os contém e cada subdiretório é um projeto. Índice, sessões de
agente, segundo cérebro, graphify, telemetria de custos, auditoria e operações de git
são escopados por projeto através de um cadastro centralizado em `project_record`.

`PROJECTS_ROOT` é a fronteira: nenhum caminho fora dela é alcançável, e o nome/slug
do projeto é validado como um único segmento — `..` e barras não passam.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import (
    AgentSessionRecord,
    AuditLogEntry,
    Document,
    GraphEdge,
    GraphNode,
    Note,
    ProjectRecord,
    RequestLog,
)
from sicoobito.logging_setup import get_logger
from sicoobito.workspace.path_guard import default_path_guard

log = get_logger(__name__)

# Um segmento de caminho, sem separador e sem `..`.
_NOME_VALIDO = re.compile(r"^[A-Za-z0-9._-][A-Za-z0-9 ._-]{0,127}$")

_IGNORADOS = {".git", "node_modules", ".venv", "__pycache__", ".sicoobito", "$RECYCLE.BIN"}


class ProjectError(ValueError):
    pass


def _is_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


@dataclass(slots=True)
class Project:
    name: str
    path: Path
    is_git: bool
    branch: str | None = None
    slug: str | None = None
    description: str = ""
    budget_limit_usd: float | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectSummary:
    slug: str
    name: str
    description: str
    local_path: str | None
    git_url: str | None
    is_git: bool
    branch: str | None
    budget_limit_usd: float | None
    total_cost_usd: float
    total_tokens: int
    notes_count: int
    documents_count: int
    graph_nodes_count: int
    graph_edges_count: int
    audit_events_count: int
    active_sessions_count: int
    recent_commits: list[dict[str, str]]
    settings: dict[str, Any]


def validate_name(name: str) -> str:
    """Aceita apenas um segmento simples. `..`, `/` e `\\` são recusados."""
    limpo = (name or "").strip()
    if not limpo or limpo in {".", ".."} or not _NOME_VALIDO.match(limpo):
        raise ProjectError(
            f"Nome de projeto inválido: {name!r}. Use apenas o nome da pasta, sem barras nem '..'."
        )
    return limpo


def resolve(projects_root: Path, name: str) -> Path:
    """Caminho absoluto do projeto, garantidamente dentro da raiz."""
    raiz = projects_root.resolve()
    valid_name = validate_name(name)
    destino = (raiz / valid_name).resolve()
    if destino != raiz and raiz not in destino.parents:
        raise ProjectError(f"Projeto fora de PROJECTS_ROOT: {name}")
    if destino.is_dir():
        return destino

    # Busca fallback insensível a maiúsculas/minúsculas
    if raiz.is_dir():
        name_lower = valid_name.lower()
        for child in raiz.iterdir():
            if child.is_dir() and child.name.lower() == name_lower:
                return child.resolve()

    raise ProjectError(f"Projeto não encontrado: {name}")


def _branch_of(path: Path) -> str | None:
    """Lê o branch direto do `.git/HEAD`."""
    head = path / ".git" / "HEAD"
    try:
        conteudo = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if conteudo.startswith("ref:"):
        return conteudo.split("/")[-1]
    return conteudo[:8] or None


def list_projects(projects_root: Path) -> list[Project]:
    """Descobre projetos no disk sob PROJECTS_ROOT (compatibilidade legada)."""
    raiz = projects_root.resolve()
    if not raiz.is_dir():
        log.warning("projects.root.missing", path=str(raiz))
        return []

    projetos: list[Project] = []
    for filho in sorted(raiz.iterdir(), key=lambda p: p.name.lower()):
        if not filho.is_dir() or filho.name in _IGNORADOS or filho.name.startswith("."):
            continue
        eh_git = (filho / ".git").exists()
        projetos.append(
            Project(
                name=filho.name,
                path=filho,
                is_git=eh_git,
                branch=_branch_of(filho) if eh_git else None,
                slug=filho.name,
            )
        )
    return projetos


def _allow_existing_dirs(paths: list[str]) -> int:
    """Parte bloqueante (stat + registro em memória) de `rehydrate_path_guard`
    — isolada para rodar em thread, já que `Path.is_dir()` é I/O síncrono."""
    count = 0
    for local_path in paths:
        if not local_path:
            continue
        path = Path(local_path)
        if path.is_dir():
            try:
                default_path_guard.allow(path)
                count += 1
            except ValueError:
                continue
    return count


async def rehydrate_path_guard(session: AsyncSession) -> int:
    """Re-registra no `PathGuard` os projetos abertos via `open-path` em
    execuções anteriores da API — o allowlist em memória não sobrevive a um
    restart; sem isto, um projeto legitimamente aberto fora de
    `PROJECTS_ROOT` perderia acesso ao próprio metadado git até ser reaberto
    manualmente pela UI."""
    registros = (await session.execute(select(ProjectRecord.local_path))).scalars().all()
    return await asyncio.to_thread(_allow_existing_dirs, list(registros))


async def sync_projects_db(session: AsyncSession, projects_root: Path) -> list[ProjectRecord]:
    """Sincroniza as pastas no filesystem com a tabela `project_record` do Postgres."""
    disk_projects = list_projects(projects_root)
    records = list((await session.execute(select(ProjectRecord))).scalars().all())
    by_slug = {r.slug: r for r in records}

    novos: list[ProjectRecord] = []
    for dp in disk_projects:
        if dp.slug not in by_slug:
            rec = ProjectRecord(
                slug=dp.slug,
                name=dp.name,
                description=f"Projeto local em {dp.path.name}",
                local_path=str(dp.path),
                default_branch=dp.branch or "main",
                settings={},
            )
            session.add(rec)
            novos.append(rec)

    if novos:
        await session.flush()
        log.info("projects.sync_db.added", count=len(novos))

    # O allowlist do PathGuard é em memória — não sobrevive a um restart do
    # processo. Este é o ponto de sincronização natural (chamado sempre que a
    # Central de Projetos lista os projetos) para re-hidratá-lo a partir do
    # que já está persistido, sem exigir que o usuário reabra manualmente
    # cada projeto que vive fora de PROJECTS_ROOT.
    await rehydrate_path_guard(session)

    stmt = select(ProjectRecord).order_by(ProjectRecord.name)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def ensure_project_slug_exists(session: AsyncSession, slug: str) -> None:
    """Levanta `ProjectError` se `slug` não corresponde a nenhum `ProjectRecord`.

    Endurecimento pré-FK: `documents`/`notes` (`project_slug`) e `graphify`
    (`workspace`, na indexação de conteúdo avulso — a varredura de diretório já
    passa por `resolve()`) hoje gravam qualquer string vinda do request sem
    checar se aponta para um projeto real, deixando a porta aberta para erro de
    digitação virar uma partição fantasma numa das quatro fontes de RAG. Uma FK
    de banco de verdade exigiria migração de backfill para não quebrar dado
    existente (ver plano de implementação); esta checagem é o passo seguro que
    já vale sozinho, sem mexer no schema.
    """
    stmt = select(ProjectRecord.id).where(ProjectRecord.slug == slug)
    encontrado = (await session.execute(stmt)).scalar_one_or_none()
    if encontrado is None:
        raise ProjectError(f"Projeto não cadastrado: {slug!r}")


async def get_project_summary(
    session: AsyncSession, slug: str, projects_root: Path
) -> ProjectSummary:
    """Consolida todas as métricas (IDE, Git, Custos, Notas, Graphify, Auditoria, Sessões)."""
    slug_valido = validate_name(slug)

    # 1. Registro no BD
    stmt_rec = select(ProjectRecord).where(ProjectRecord.slug == slug_valido)
    rec = (await session.execute(stmt_rec)).scalar_one_or_none()
    if not rec:
        # Se pasta existe no disk, auto-registra
        try:
            path = resolve(projects_root, slug_valido)
            rec = ProjectRecord(
                slug=slug_valido,
                name=slug_valido,
                description=f"Projeto em {path.name}",
                local_path=str(path),
                default_branch=_branch_of(path) or "main",
            )
            session.add(rec)
            await session.flush()
        except ProjectError as err:
            msg = f"Projeto {slug_valido!r} não cadastrado e não encontrado no filesystem."
            raise ProjectError(msg) from err

    # 2. Informações de Git local
    local_path = Path(rec.local_path) if rec.local_path else (projects_root / rec.slug)
    # `local_path` pode ter sido registrado fora de PROJECTS_ROOT via
    # `/api/projects/open-path` — nesse caso, só ler metadado git dele se o
    # PathGuard confirma que essa pasta foi explicitamente autorizada (o
    # controle existia mas nunca era consultado; sem isto, qualquer
    # ProjectRecord com `local_path` fora da raiz teria seu branch/commits
    # lidos sem nenhuma checagem).
    caminho_autorizado = _is_within(local_path, projects_root) or default_path_guard.is_allowed(
        local_path
    )
    is_git = caminho_autorizado and (local_path / ".git").exists()
    branch = _branch_of(local_path) if is_git else None

    # 3. Telemetria de Custos
    stmt_custo = select(func.coalesce(func.sum(RequestLog.cost_usd), 0.0)).where(
        RequestLog.project_slug == rec.slug
    )
    custo_total = (await session.execute(stmt_custo)).scalar() or 0.0

    stmt_tokens = select(func.coalesce(func.sum(RequestLog.total_tokens), 0)).where(
        RequestLog.project_slug == rec.slug
    )
    tokens_total = (await session.execute(stmt_tokens)).scalar() or 0

    # 4. Notas (Segundo Cérebro)
    notes_count = (
        await session.execute(select(func.count(Note.id)).where(Note.project_slug == rec.slug))
    ).scalar() or 0

    # 4b. Documentos (RAG)
    documents_count = (
        await session.execute(
            select(func.count(Document.id)).where(Document.project_slug == rec.slug)
        )
    ).scalar() or 0

    # 5. Graphify (Grafo de Conhecimento)
    graph_nodes = (
        await session.execute(
            select(func.count(GraphNode.id)).where(GraphNode.workspace == rec.slug)
        )
    ).scalar() or 0

    graph_edges = (
        await session.execute(
            select(func.count(GraphEdge.id)).where(GraphEdge.workspace == rec.slug)
        )
    ).scalar() or 0

    # 6. Auditoria
    audit_count = (
        await session.execute(
            select(func.count(AuditLogEntry.id)).where(AuditLogEntry.project_slug == rec.slug)
        )
    ).scalar() or 0

    # 7. Sessões Ativas do Agente
    sessions_active = (
        await session.execute(
            select(func.count(AgentSessionRecord.session_id)).where(
                AgentSessionRecord.project == rec.slug,
                AgentSessionRecord.status == "open",
            )
        )
    ).scalar() or 0

    # 8. Git Intelligence — poucos commits recentes, best-effort: sem Git ou
    # repositório inválido não pode derrubar o resumo do projeto.
    recent_commits: list[dict[str, str]] = []
    if is_git:
        try:
            from sicoobito.workspace import git as git_ops

            recent_commits = await asyncio.to_thread(git_ops.log_recent, local_path, 5)
        except Exception as exc:
            log.warning("projects.summary.git_log_failed", slug=rec.slug, error=str(exc)[:200])

    return ProjectSummary(
        slug=rec.slug,
        name=rec.name,
        description=rec.description or "",
        local_path=str(local_path),
        git_url=rec.git_url,
        is_git=is_git,
        branch=branch,
        budget_limit_usd=float(rec.budget_limit_usd) if rec.budget_limit_usd is not None else None,
        total_cost_usd=float(custo_total),
        total_tokens=int(tokens_total),
        notes_count=int(notes_count),
        documents_count=int(documents_count),
        graph_nodes_count=int(graph_nodes),
        graph_edges_count=int(graph_edges),
        audit_events_count=int(audit_count),
        active_sessions_count=int(sessions_active),
        recent_commits=recent_commits,
        settings=rec.settings or {},
    )
