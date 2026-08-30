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
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.db.models import (
    AgentSessionRecord,
    AuditLogEntry,
    Document,
    GraphEdge,
    GraphNode,
    Note,
    ProjectRecord,
    RequestLog,
)
from eltanix.logging_setup import get_logger
from eltanix.workspace.path_guard import default_path_guard

log = get_logger(__name__)

# Um segmento de caminho, sem separador e sem `..`.
_NOME_VALIDO = re.compile(r"^[A-Za-z0-9._-][A-Za-z0-9 ._-]{0,127}$")

_IGNORADOS = {".git", "node_modules", ".venv", "__pycache__", ".eltanix", "$RECYCLE.BIN"}


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


def slugify(name: str) -> str:
    """Nome de exibição → slug kebab-case (`"Meu Projeto"` → `"meu-projeto"`):
    minúsculas, acento removido, tudo que não é `[a-z0-9-]` vira hífen,
    hífens redundantes colapsam.

    Só usado ao CRIAR um slug novo (`create_project`/`open-path`) — antes,
    `slug` era o `name` cru, com espaço e maiúscula indo direto pro nome da
    pasta em disco e pras chaves de partição do RAG (`project_slug` em
    `Note`/`Document`/etc.). `validate_name` continua aceitando o charset
    mais largo (inclui espaço) de propósito: projeto já cadastrado com um
    slug antigo, sem passar por esta função, precisa continuar resolvendo."""
    normalizado = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    kebab = re.sub(r"[^a-z0-9]+", "-", normalizado.lower()).strip("-")
    return kebab or "projeto"


# Cache em memória slug -> `local_path` absoluto (ADR 0016) — MESMO padrão já
# usado por `default_path_guard` logo abaixo: um registry de processo,
# rehidratado do Postgres na subida (`main.py::lifespan`) e sempre que a
# Central de Projetos lista (`sync_projects_db`). Existe porque `resolve()` é
# chamado de ~8 lugares síncronos, sem sessão de banco à mão (dependências
# FastAPI, funções de workspace, etc.) — threadar `AsyncSession` por todos
# eles pra ler `ProjectRecord.local_path` a cada chamada seria um refactor
# muito maior só pra obter o mesmo resultado que este cache dá de graça.
_slug_to_local_path: dict[str, str] = {}


def register_local_path(slug: str, local_path: str | None) -> None:
    """Atualiza o cache acima. Chamado pelas rotas que gravam/apagam
    `ProjectRecord.local_path` (`open-path`, `delete`) pra manter `resolve()`
    consistente com o Postgres sem esperar a próxima rehidratação."""
    if local_path:
        _slug_to_local_path[slug] = local_path
    else:
        _slug_to_local_path.pop(slug, None)


def resolve(projects_root: Path, name: str) -> Path:
    """Caminho absoluto do projeto.

    `ProjectRecord.local_path` é a fonte de verdade (ADR 0016): se `name` é o
    slug de um projeto vinculado fora de `PROJECTS_ROOT` via `open-path` — e
    esse caminho ainda existe e está autorizado no `PathGuard` — ele vence.
    Senão, cai no comportamento legado: `PROJECTS_ROOT / <nome>` (com
    fallback insensível a maiúsculas/minúsculas), que também é o que sempre
    foi usado para todo projeto criado por `create_project` (`local_path`
    sempre é `PROJECTS_ROOT/<slug>` nesse caso, então o cache nem entra em
    jogo — a checagem de containment abaixo continua valendo pra esse caminho)."""
    valid_name = validate_name(name)

    cached = _slug_to_local_path.get(valid_name)
    if cached:
        candidate = Path(cached)
        if candidate.is_dir() and (
            _is_within(candidate, projects_root) or default_path_guard.is_allowed(candidate)
        ):
            return candidate.resolve()

    raiz = projects_root.resolve()
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


def _allow_existing_dirs(records: list[tuple[str, str | None]]) -> int:
    """Parte bloqueante (stat + registro em memória) de `rehydrate_path_guard`
    — isolada para rodar em thread, já que `Path.is_dir()` é I/O síncrono.
    Popula os dois registries de processo a partir do que já está persistido:
    o `PathGuard` (autorização) e `_slug_to_local_path` (ADR 0016 — de onde
    `resolve()` lê `local_path` sem precisar de sessão de banco)."""
    count = 0
    for slug, local_path in records:
        if not local_path:
            continue
        path = Path(local_path)
        if path.is_dir():
            try:
                default_path_guard.allow(path)
            except ValueError:
                continue
            register_local_path(slug, local_path)
            count += 1
    return count


async def rehydrate_path_guard(session: AsyncSession) -> int:
    """Re-registra no `PathGuard`/`_slug_to_local_path` os projetos abertos
    via `open-path` em execuções anteriores da API — nenhum dos dois
    registries em memória sobrevive a um restart; sem isto, um projeto
    legitimamente aberto fora de `PROJECTS_ROOT` perderia acesso ao próprio
    metadado git (e a tudo mais que `resolve()` alimenta — arquivos, agente,
    índice, LSP) até ser reaberto manualmente pela UI."""
    registros = (
        await session.execute(select(ProjectRecord.slug, ProjectRecord.local_path))
    ).all()
    return await asyncio.to_thread(_allow_existing_dirs, [(r[0], r[1]) for r in registros])


async def sync_projects_db(session: AsyncSession, projects_root: Path) -> list[ProjectRecord]:
    """Sincroniza as pastas no filesystem com a tabela `project_record` do Postgres.

    Pasta nova sob `PROJECTS_ROOT` não tem dono natural — sem `ProjectMember`,
    o projeto fica "órfão" (RBAC nega qualquer membro comum, só admin/serviço
    enxergam, ver `list_projects` em `api/routes/projects.py`). Em vez de um
    fluxo de "claim" separado, atribui-se `owner` ao admin da instância
    (o usuário seed, `AuthService.ensure_seed_user`) na hora da descoberta —
    ver ADR 0016. Sem admin cadastrado ainda (banco vazio), fica mesmo
    órfão até o seed rodar.
    """
    from eltanix.db.models import AppUser, ProjectMember

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
        admin_id = (
            await session.execute(
                select(AppUser.id).where(AppUser.is_admin.is_(True)).order_by(AppUser.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if admin_id is not None:
            for rec in novos:
                session.add(ProjectMember(project_id=rec.id, user_id=admin_id, role="owner"))
        log.info("projects.sync_db.added", count=len(novos), owner_assigned=admin_id is not None)

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


async def find_orphaned_project_data(
    session: AsyncSession, *, slug: str, workspace_path: str | None = None
) -> list[str]:
    """Nomes (legíveis) das fontes de dado que ainda têm registro sob `slug`
    (ou `workspace_path`) sem nenhum `ProjectRecord` dono — `delete_project`
    só apaga o `ProjectRecord`; `Note`/`Document`/`AuditLogEntry`/
    `RequestLog` (`project_slug`) e `AgentSessionRecord` (`project`) e
    `IndexedFile`/`CodeChunk` (`workspace`, convenção de
    `context/indexer.py::workspace_key` — caminho absoluto, ao contrário de
    `GraphNode`/`GraphEdge`, que usam o slug) não têm FK pra isso, então
    continuam existindo (ver `ensure_project_slug_exists` acima pro contexto
    completo).

    Usado para BLOQUEAR reaproveitar um slug recém-apagado antes de uma FK de
    verdade existir: sem isto, `create_project`/`open-path` criando um
    `ProjectRecord` novo com o mesmo slug faria esse projeto "herdar" nota,
    documento, grafo, auditoria e custo do projeto morto, silenciosamente.

    Cobre as fontes primárias de cada uma das quatro origens de RAG mais
    auditoria/custo — não every tabela auxiliar (`DocumentChunk`/`NoteChunk`/
    `CodeEdge`/`GraphChunkMapping`/`GraphMetrics` seguem a mesma chave da
    tabela pai e ficam implícitas: se a pai está limpa, a auxiliar também
    está, pela FK que ELAS têm entre si)."""
    from eltanix.db.models import CodeChunk, IndexedFile

    achados: list[str] = []

    por_slug: list[tuple[str, Any]] = [
        ("notas (Segundo Cérebro)", Note.project_slug),
        ("documentos (RAG)", Document.project_slug),
        ("eventos de auditoria", AuditLogEntry.project_slug),
        ("telemetria de custo", RequestLog.project_slug),
        ("sessões do agente", AgentSessionRecord.project),
        ("grafo de conhecimento (Graphify)", GraphNode.workspace),
    ]
    for label, coluna in por_slug:
        existe = (await session.execute(select(coluna).where(coluna == slug).limit(1))).first()
        if existe:
            achados.append(label)

    if workspace_path:
        por_workspace: list[tuple[str, Any]] = [
            ("índice semântico de código", IndexedFile.workspace),
            ("chunks de código indexados", CodeChunk.workspace),
        ]
        for label, coluna in por_workspace:
            existe = (
                await session.execute(select(coluna).where(coluna == workspace_path).limit(1))
            ).first()
            if existe:
                achados.append(label)

    return achados


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
            from eltanix.workspace import git as git_ops

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
