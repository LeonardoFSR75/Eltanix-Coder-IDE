"""Rotas de gestão centralizada de projetos."""

from __future__ import annotations

import asyncio
import os
import shutil
import string
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.api.deps import AdminDep, AuthDep
from eltanix.audit.service import AuditService
from eltanix.auth import store as auth_store
from eltanix.auth.rbac import ROLE_RANK, require_role_by_slug
from eltanix.config import get_settings
from eltanix.db.models import ProjectRecord
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.security.url_safety import validate_target_url
from eltanix.workspace.projects import (
    ProjectError,
    _branch_of,
    find_orphaned_project_data,
    get_project_summary,
    register_local_path,
    resolve,
    slugify,
    sync_projects_db,
    validate_name,
)
from eltanix.workspace.projects import (
    list_projects as list_disk_projects,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[AuthDep])

# Referências fortes para as tasks de provisionamento de ambiente disparadas em
# segundo plano por `create_project` — sem isto, `asyncio` pode coletar a task
# antes dela terminar (mesmo padrão de `telemetry/tracer.py::TraceRecorder`).
_env_provision_tasks: set[asyncio.Task[None]] = set()


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


async def _provision_env_background(target_path: Path, language: str | None, slug: str) -> None:
    """Provisiona `.venv`/`node_modules`/etc. sem bloquear `POST /projects` — ver
    o comentário no chamador. Falha aqui é sempre não-fatal: o pior caso é o
    ambiente ficar pendente até o próximo prewarm ou até a IDE ser aberta."""
    try:
        from eltanix.api.routes.packages import ensure_project_env

        await ensure_project_env(target_path, language)
    except Exception as exc:
        log.warning("projects.auto_env.failed", slug=slug, error=str(exc)[:200])


def _projects_root(request: Request) -> Path:
    raiz = getattr(request.app.state, "projects_root", None) or get_settings().projects_root
    if isinstance(raiz, Path):
        return raiz
    if raiz:
        return Path(str(raiz))
    return Path(".")


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    language: str | None = Field(
        default=None,
        description="Linguagem/ecossistema do projeto: python, nodejs, typescript, go, rust, php",
    )
    git_url: str | None = Field(default=None)
    init_git: bool = Field(default=True, description="Inicializa repositório Git automaticamente")
    create_github_repo: bool = Field(
        default=False, description="Cria repositório remoto PRIVADO no GitHub automaticamente"
    )
    clone: bool = Field(
        default=False,
        description=(
            "Clona o conteúdo de `git_url` de verdade (`git clone`) em vez de só "
            "inicializar um repositório vazio local apontando `origin` pra lá — "
            "aba 'Clonar do Git' do LinkProjectModal (ADR 0016, Fase 4)."
        ),
    )
    git_token: str | None = Field(
        default=None,
        description=(
            "Token opcional pra clonar repositório privado. Usado uma única vez "
            "pra montar a URL autenticada do clone; nunca persistido em "
            "`ProjectRecord.git_url` nem logado."
        ),
    )
    budget_limit_usd: float | None = Field(default=None)
    settings: dict[str, Any] = Field(default_factory=dict)


class OpenPathIn(BaseModel):
    path: str = Field(min_length=1, description="Caminho absoluto de qualquer pasta do SO")


class BrowsePathIn(BaseModel):
    path: str | None = Field(default=None, description="Caminho a explorar — vazio lista unidades/raízes do sistema")


class InspectPathIn(BaseModel):
    path: str = Field(min_length=1, description="Caminho a inspecionar")


def _list_system_roots(projects_root: Path) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    if projects_root.exists():
        roots.append({
            "name": f"⚡ Raiz de Projetos ({projects_root.name})",
            "path": str(projects_root),
            "icon": "projects",
            "type": "projects_root",
        })
    user_home = Path.home()
    roots.append({
        "name": f"🏠 Pasta do Usuário ({user_home.name})",
        "path": str(user_home),
        "icon": "home",
        "type": "home",
    })
    docs = user_home / "Documents"
    if docs.exists():
        roots.append({
            "name": "📁 Documentos",
            "path": str(docs),
            "icon": "docs",
            "type": "special",
        })
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append({
                    "name": f"💽 Disco Local ({letter}:)",
                    "path": str(drive),
                    "icon": "drive",
                    "type": "drive",
                })
    else:
        roots.append({
            "name": "💽 Raiz do Sistema (/)",
            "path": "/",
            "icon": "drive",
            "type": "drive",
        })
    return roots


def _resolve_user_path(raw_path: str, projects_root: Path) -> Path:
    """Resolve qualquer caminho informado pelo usuário com suporte a:
    1. Nome simples de pasta ou subcaminho, sob a raiz de projetos (ex: 'Sorteador' -> projects_root / 'Sorteador')
    2. Caminhos absolutos do host Windows (ex: 'C:\\Users\\...\\Projetos\\Sorteador') mapeados para /projects
    3. Caminhos diretos do container / SO (ex: '/projects/Sorteador', 'D:\\work\\outro-projeto')

    Esta função alimenta `open-path` (que vincula a pasta devolvida como
    projeto) e `browse`/`inspect` — por isso NÃO tem um passo de "se nada
    bateu, tenta achar uma pasta com esse *nome* em `projects_root`": isso já
    existiu aqui e causava vinculação silenciosa da pasta errada sempre que o
    caminho pedido não resolvia (ex.: o seletor nativo do browser, que só
    consegue entregar o NOME da pasta escolhida — nunca o caminho completo —
    fazia todo `/projects/<nome-coincidente>` existente "vencer" no lugar da
    pasta que o usuário via na tela; ver `LinkProjectModal.tsx`)."""
    clean = (raw_path or "").strip().strip("'\"")
    if not clean:
        return projects_root

    # 1. Se for apenas o nome da pasta ou subcaminho sob a raiz de projetos.
    # `..` seria "resolvido" para fora de `projects_root` por `.resolve()`
    # sozinho — o `is_relative_to` abaixo é o que garante que este passo só
    # aceita algo realmente dentro da raiz, nunca uma fuga por travessia.
    candidate_in_root = (projects_root / clean).resolve()
    if (
        candidate_in_root.exists()
        and candidate_in_root.is_dir()
        and candidate_in_root.is_relative_to(projects_root.resolve())
    ):
        return candidate_in_root

    # 2. Tradução de caminhos Windows (se estiver rodando dentro do container Docker)
    norm = clean.replace("\\", "/")
    projects_root_host = os.environ.get("PROJECTS_ROOT_HOST", "")
    if projects_root_host:
        host_norm = projects_root_host.replace("\\", "/").rstrip("/")
        if norm.lower().startswith(host_norm.lower()):
            rel_part = norm[len(host_norm):].lstrip("/")
            target = (projects_root / rel_part).resolve()
            if target.exists() and target.is_relative_to(projects_root.resolve()):
                return target

    # 3. Resolução direta pelo filesystem do sistema operacional
    try:
        direct = Path(clean).expanduser().resolve()
        if direct.exists():
            return direct
    except Exception:
        pass

    return candidate_in_root



class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    git_url: str | None = Field(default=None)
    budget_limit_usd: float | None = Field(default=None)
    settings: dict[str, Any] | None = Field(default=None)


@router.get("")
async def list_projects(request: Request) -> dict[str, Any]:
    """Lista todos os projetos cadastrados no Postgres (auto-sincronizados com PROJECTS_ROOT)."""
    projects_root = _projects_root(request)
    is_privileged = getattr(request.state, "is_service", False) or getattr(
        request.state, "is_admin", False
    )
    try:
        async with session_scope() as session:
            records = await sync_projects_db(session, projects_root)
            # Canal de serviço e admin da instância veem tudo (mesmo bypass de
            # `auth/rbac.py`); um usuário convidado comum só vê projeto onde é
            # `project_member` — sem isso, RBAC restringiria escrita mas
            # continuaria vazando a existência de todo projeto na listagem.
            user_id = getattr(request.state, "user_id", None)
            roles_por_projeto: dict[uuid.UUID, str] = {}
            if not is_privileged:
                if user_id is not None:
                    from eltanix.db.models import ProjectMember

                    stmt_membros = select(ProjectMember).where(ProjectMember.user_id == user_id)
                    roles_por_projeto = {
                        m.project_id: m.role for m in (await session.execute(stmt_membros)).scalars()
                    }
                    records = [r for r in records if r.id in roles_por_projeto]
                else:
                    records = []
            items: list[dict[str, Any]] = []
            for r in records:
                # Front usa isto pra avisar "pasta não encontrada" — pasta
                # vinculada (ou movida/apagada fora da IDE) some do disco sem
                # que ninguém apague o cadastro (`local_path` não tem
                # invariante de existência, ver ADR 0016).
                caminho_local = Path(r.local_path) if r.local_path else None
                local_path_exists = caminho_local is not None and caminho_local.exists()
                items.append(
                    {
                        "id": str(r.id),
                        "slug": r.slug,
                        "name": r.name,
                        "description": r.description,
                        "local_path": r.local_path,
                        "local_path_exists": local_path_exists,
                        "git_url": r.git_url,
                        "default_branch": r.default_branch,
                        "budget_limit_usd": float(r.budget_limit_usd)
                        if r.budget_limit_usd is not None
                        else None,
                        "settings": r.settings,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                        # `owner` pra admin/serviço só pra a UI saber que pode
                        # gerenciar (apagar, mudar membro) — RBAC de verdade
                        # continua sendo decidido servidor-side em cada rota,
                        # isto é só uma dica pra esconder botão que ia 403.
                        "my_role": "owner" if is_privileged else roles_por_projeto.get(r.id),
                    }
                )
        return {"projects": items}
    except Exception as exc:
        log.warning("projects.db.unavailable", error=str(exc))
        disk_projects = list_disk_projects(projects_root)
        items = [
            {
                "id": p.slug or p.name,
                "slug": p.slug or p.name,
                "name": p.name,
                "description": p.description,
                "local_path": str(p.path),
                "local_path_exists": True,
                "git_url": None,
                "default_branch": p.branch or "main",
                "budget_limit_usd": None,
                "settings": {},
                # Banco fora do ar: sem Postgres não dá pra checar RBAC nem
                # apagar registro nenhum — `my_role` fica `None` de propósito
                # (a UI esconde ação que dependa dele).
                "my_role": None,
            }
            for p in disk_projects
        ]
        return {"projects": items}


async def _guard_create_github_repo(request: Request) -> None:
    """`create_github_repo` cria um repositório PRIVADO na conta GitHub da
    INSTÂNCIA (`settings.github_token`), não do usuário — restrito a admin/
    canal de serviço, mesmo bypass de `auth/rbac.py::_actor_bypasses`. Sem
    isto, qualquer sessão autenticada podia criar repositório na conta do
    dono da instância só marcando uma flag no payload."""
    if getattr(request.state, "is_service", False) or getattr(request.state, "is_admin", False):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Criar repositório no GitHub da instância requer administrador.",
    )


@router.post("")
async def create_project(payload: ProjectCreateIn, request: Request) -> dict[str, Any]:
    """Cadastra um novo projeto e cria a pasta correspondente sob PROJECTS_ROOT."""
    projects_root = _projects_root(request)
    try:
        raw_slug = validate_name(payload.name)
    except ProjectError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    # Slug NOVO sempre nasce kebab-case (`"Meu Projeto"` → `"meu-projeto"`) —
    # `raw_slug` (o nome cru, convenção anterior à slugificação) só é usado
    # abaixo pra continuar num projeto que já existe sob ele, sem duplicar.
    kebab_slug = slugify(payload.name)

    if payload.create_github_repo:
        await _guard_create_github_repo(request)

    # Checagem de permissão ANTES de qualquer efeito colateral (mkdir,
    # provisionamento de ambiente, git init, criação de repo no GitHub). Na
    # ordem antiga, um POST pra um slug alheio já tinha criado a pasta,
    # disparado provisionamento e inicializado git ANTES do 403 de
    # `require_role_by_slug` no ramo de upsert — os efeitos ficavam mesmo com
    # a requisição barrada. Também é aqui que uma falha de Postgres é
    # detectada: falha rápido com 503 em vez de seguir criando artefatos
    # reais em disco pra, no fim, devolver 200 com um registro fabricado que
    # nunca foi persistido (o que o `except Exception` genérico fazia antes).
    slug = kebab_slug
    try:
        async with session_scope() as session:
            if raw_slug != kebab_slug:
                # Já existe um `ProjectRecord` sob o slug "cru" (criado antes
                # desta mudança)? Continua nele — reenviar o mesmo `name` de
                # sempre não pode virar um projeto duplicado só porque o slug
                # novo seria diferente.
                stmt_raw = select(ProjectRecord.slug).where(ProjectRecord.slug == raw_slug)
                if (await session.execute(stmt_raw)).scalar_one_or_none() is not None:
                    slug = raw_slug

            target_path = projects_root / slug

            stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                # POST é upsert-por-slug: sem esta checagem, um `editor` (ou
                # qualquer autenticado, hoje) reenviando o mesmo nome
                # reescreveria metadado de um projeto que não é dono.
                await require_role_by_slug(
                    session, request, project_slug=slug, min_role="editor"
                )
            else:
                # Slug novo, mas pode ter sido apagado antes (`delete_project`
                # só remove o `ProjectRecord`, não nota/documento/grafo/
                # auditoria/custo — sem FK, ver `find_orphaned_project_data`).
                # Sem este bloqueio, o projeto novo "herdaria" silenciosamente
                # o histórico do projeto morto.
                orfaos = await find_orphaned_project_data(
                    session,
                    slug=slug,
                    workspace_path=str(target_path.resolve()).replace("\\", "/"),
                )
                if orfaos:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"O slug '{slug}' já teve um projeto apagado, mas ainda existe dado "
                            f"associado a ele em: {', '.join(orfaos)}. Escolha outro nome, ou peça "
                            "a um administrador para limpar esse histórico antes de reusar o slug."
                        ),
                    )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("projects.db.unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados indisponível — não é possível cadastrar o projeto agora.",
        ) from exc

    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    # Disparado em segundo plano, não aguardado: criar o venv/ambiente pode levar
    # dezenas de segundos (mount de bind do Windows é lento para muitos arquivos
    # pequenos), e `POST /{slug}/prewarm` já refaz esta mesma chamada quando o
    # usuário abre o projeto na IDE — bloquear a criação do projeto nisso é
    # latência pura sem ganho duradouro. `ensure_venv`/`ensure_node_env` etc. já
    # são idempotentes (checam se o ambiente existe antes de recriar).
    _task = asyncio.create_task(_provision_env_background(target_path, payload.language, slug))
    _env_provision_tasks.add(_task)
    _task.add_done_callback(_env_provision_tasks.discard)

    effective_git_url = payload.git_url

    if payload.clone and payload.git_url:
        # ADR 0016, Fase 4: a aba "Clonar do Git" prometia baixar o conteúdo
        # do repositório, mas até aqui só fazia `git init` + `remote add
        # origin` numa pasta vazia — nunca puxava um único arquivo. `clone`
        # é o sinal explícito de que o chamador quer o conteúdo de verdade.
        try:
            validate_target_url(payload.git_url)
        except ValueError as exc:
            shutil.rmtree(target_path, ignore_errors=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        clone_url = payload.git_url
        if payload.git_token:
            # Token embutido só nesta URL efêmera (nunca persistida) — jeito
            # padrão do Git de autenticar HTTPS sem `GIT_ASKPASS`/credential
            # helper. `validate_target_url` já garantiu http(s)-only acima,
            # então `parsed.netloc` sempre existe aqui.
            parsed = urllib.parse.urlsplit(clone_url)
            netloc_com_token = f"{payload.git_token}@{parsed.netloc}"
            clone_url = urllib.parse.urlunsplit(
                (parsed.scheme, netloc_com_token, parsed.path, parsed.query, parsed.fragment)
            )

        try:
            from git import Repo

            await asyncio.wait_for(
                asyncio.to_thread(Repo.clone_from, clone_url, target_path),
                timeout=300,
            )
        except Exception as exc:
            # `_provision_env_background` já foi disparada sobre esta pasta —
            # ela é best-effort e tolera a pasta sumir no meio (falha vira só
            # um log, ver o próprio `_provision_env_background`), mas cancelar
            # aqui evita trabalho às cegas.
            _task.cancel()
            shutil.rmtree(target_path, ignore_errors=True)
            if isinstance(exc, TimeoutError):
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Clone excedeu o tempo limite (5 min) — verifique a URL e a conectividade.",
                ) from exc
            # `GitCommandError`/stderr do git costuma ecoar a URL completa —
            # com o token embutido, se veio um. Nunca repassar `str(exc)` bruto
            # pro cliente nem pro log; `effective_git_url` (sem token) já basta
            # pra diagnosticar.
            log.warning("git.clone.failed", slug=slug, git_url=effective_git_url)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Falha ao clonar '{effective_git_url}' — verifique a URL, "
                    "credenciais e se o repositório existe."
                ),
            ) from exc

    elif payload.init_git and not (target_path / ".git").exists():
        try:
            from git import Repo

            repo = Repo.init(target_path)
            try:
                gitignore_path = target_path / ".gitignore"
                if not gitignore_path.exists():
                    gitignore_path.write_text(
                        ".eltanix/\nnode_modules/\n__pycache__/\n", encoding="utf-8"
                    )
                repo.index.add([str(gitignore_path.relative_to(target_path))])
                repo.index.commit("Initial commit")
            except Exception as exc:
                log.warning("git.initial_commit.failed", path=str(target_path), error=str(exc))

            if payload.create_github_repo and not effective_git_url:
                try:
                    from eltanix.workspace.github import GitHubClient, resolve_token

                    settings = get_settings()
                    token = await resolve_token(settings.github_token)
                    if token:
                        gh = GitHubClient(token)
                        repo_data = await gh.create_repository(
                            name=slug,
                            description=payload.description,
                            private=True,
                        )
                        effective_git_url = repo_data.get("clone_url") or repo_data.get("html_url")
                except Exception as exc:
                    log.warning("github.private_repo.create_failed", slug=slug, error=str(exc))

            if effective_git_url:
                try:
                    repo.create_remote("origin", effective_git_url)
                except Exception as exc:
                    log.warning("git.remote.create_failed", path=str(target_path), error=str(exc))
        except Exception as exc:
            log.warning("git.init.failed", path=str(target_path), error=str(exc))

    try:
        async with session_scope() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
            rec = (await session.execute(stmt)).scalar_one_or_none()
            user_id = getattr(request.state, "user_id", None)
            if not rec:
                rec = ProjectRecord(
                    slug=slug,
                    name=payload.name,
                    description=payload.description,
                    local_path=str(target_path),
                    git_url=effective_git_url,
                    budget_limit_usd=payload.budget_limit_usd,
                    settings=payload.settings,
                )
                session.add(rec)
                await session.flush()
                # Quem cria vira dono — sem isto, o próprio criador ficaria
                # sem `project_member` e cairia no "sem acesso" do enforcement
                # (`require_role_by_slug`) na primeira operação de escrita.
                # Ausente para o canal de serviço (`user_id is None`): não é
                # "membro" de projeto nenhum, já tem bypass total.
                if user_id is not None:
                    await auth_store.add_member(
                        session, project_id=rec.id, user_id=user_id, role="owner"
                    )
            else:
                # Segunda checagem (a primeira, antes de qualquer efeito
                # colateral, está no topo da rota) — cobre a corrida entre um
                # POST concorrente ter criado o registro entre as duas. POST
                # é upsert-por-slug: sem isto, um `editor` (ou qualquer
                # autenticado) reenviando o mesmo nome reescreveria metadado
                # de um projeto que não é dono.
                await require_role_by_slug(session, request, project_slug=slug, min_role="editor")
                rec.name = payload.name
                rec.description = payload.description
                rec.git_url = effective_git_url
                rec.budget_limit_usd = payload.budget_limit_usd
                rec.settings = payload.settings

            await session.flush()
            await session.refresh(rec)

            budget_limit = float(rec.budget_limit_usd) if rec.budget_limit_usd is not None else None
            res = {
                "id": str(rec.id),
                "slug": rec.slug,
                "name": rec.name,
                "description": rec.description,
                "local_path": rec.local_path,
                "git_url": rec.git_url,
                "budget_limit_usd": budget_limit,
                "settings": rec.settings,
            }
    except HTTPException:
        # `require_role_by_slug` levanta 403 acima — sem este re-raise, o
        # `except Exception` genérico logo abaixo a engoliria e devolveria
        # 503 no lugar do 403, deixando RBAC sem efeito nenhum aqui.
        raise
    except Exception as exc:
        # A pasta e o `.git` (se pedidos) já foram criados em disco a essa
        # altura — não dá mais pra "cancelar" isso, mas não fabricamos mais
        # um 200 fingindo que o cadastro no Postgres também aconteceu (antes:
        # devolvia um registro que nunca foi persistido, sem `project_member`
        # nenhum — a primeira operação de escrita no projeto batia num 403
        # "sem acesso" que fazia zero sentido pra quem tinha acabado de
        # "criar" o projeto).
        log.error("projects.db.unavailable_on_create", slug=slug, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Pasta '{slug}' criada em disco, mas o banco de dados está indisponível — "
                "o cadastro não foi salvo. Tente novamente em instantes."
            ),
        ) from exc

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="create",
                details=f"Projeto cadastrado: {slug}",
                metadata={"slug": slug, "git_url": payload.git_url},
                project_slug=slug,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return res


def _reject_filesystem_root(alvo: Path) -> None:
    """`PathGuard.allow()` (chamado logo abaixo) ADICIONA `alvo` à allowlist
    global do processo — não é uma validação, é uma concessão permanente de
    acesso a tudo dentro dele. Autorizar a raiz de um drive (`C:\\`), `/` ou a
    pasta do usuário inteira faria esse `allow()` liberar o disco todo (ou o
    `$HOME` todo) pro resto da vida do processo. `AdminDep` no router já
    restringe quem chega aqui a dono da instância / canal de serviço; isto é
    a segunda camada, que barra o alvo mais perigoso mesmo vindo de um admin
    legítimo por engano."""
    if alvo.parent == alvo:  # raiz de filesystem: "/" ou "C:\\"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é permitido vincular a raiz de um disco ou do sistema de arquivos.",
        )
    if alvo == Path.home().resolve():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é permitido vincular a pasta inteira do usuário — escolha uma subpasta.",
        )


@router.post("/open-path", dependencies=[AdminDep])
async def open_absolute_path(payload: OpenPathIn, request: Request) -> dict[str, Any]:
    """Abre e autoriza qualquer pasta do SO como projeto — fora de PROJECTS_ROOT.

    Diferente de `create_project`, o caminho não precisa estar sob PROJECTS_ROOT:
    a fronteira de segurança aqui é o `PathGuard` (autorização explícita por
    caminho), não `resolve()`. O registro em `ProjectRecord` é o que faz essa
    pasta aparecer na Central de Projetos depois de aberta.

    Restrita a `AdminDep` (dono da instância / canal de serviço): o
    `PathGuard.allow()` abaixo concede acesso de leitura a QUALQUER caminho do
    host para o processo inteiro, não só para quem pediu — não é algo que uma
    sessão comum (`viewer`/`editor`) deveria poder disparar.
    """
    from eltanix.workspace.inspector import ProjectInspector
    from eltanix.workspace.path_guard import default_path_guard

    projects_root = _projects_root(request)
    alvo = await asyncio.to_thread(lambda: _resolve_user_path(payload.path, projects_root))
    if not alvo.exists() or not alvo.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho não encontrado ou não é diretório: {payload.path}",
        )
    _reject_filesystem_root(alvo)

    default_path_guard.allow(alvo)

    inspector = ProjectInspector()
    sig = inspector.inspect(alvo)

    slug = slugify(alvo.name)

    async with session_scope() as session:
        # Procura primeiro por `local_path` — não por slug: é a MESMA pasta
        # física, então é o mesmo projeto, não importa sob qual slug ela foi
        # registrada da primeira vez (inclusive um slug da convenção antiga,
        # anterior a `slugify` existir). Sem isto, reabrir a mesma pasta
        # externa duas vezes podia criar um SEGUNDO `ProjectRecord` pra ela,
        # só porque o algoritmo de derivar slug a partir do nome mudou.
        stmt_path = select(ProjectRecord).where(ProjectRecord.local_path == str(alvo))
        rec = (await session.execute(stmt_path)).scalar_one_or_none()
        if rec:
            slug = rec.slug

        if not rec:
            stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
            rec = (await session.execute(stmt)).scalar_one_or_none()
            if rec and rec.local_path != str(alvo):
                # Slug já usado por outra pasta — sufixa para não colidir.
                base_slug, suffix = slug, 2
                while rec and rec.local_path != str(alvo):
                    slug = f"{base_slug}-{suffix}"
                    stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
                    rec = (await session.execute(stmt)).scalar_one_or_none()
                    suffix += 1

        if not rec:
            # Mesmo bloqueio de `create_project`: slug livre pode ter sido
            # apagado antes, com dado órfão ainda vivo em outra tabela (sem
            # FK) — ver `find_orphaned_project_data`.
            orfaos = await find_orphaned_project_data(
                session, slug=slug, workspace_path=str(alvo).replace("\\", "/")
            )
            if orfaos:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"O slug '{slug}' já teve um projeto apagado, mas ainda existe dado "
                        f"associado a ele em: {', '.join(orfaos)}. Renomeie a pasta, ou peça a um "
                        "administrador para limpar esse histórico antes de reabrir aqui."
                    ),
                )
            rec = ProjectRecord(
                slug=slug,
                name=sig.name,
                description=sig.executive_summary or "",
                local_path=str(alvo),
                default_branch="main",
            )
            session.add(rec)
            await session.flush()
            user_id = getattr(request.state, "user_id", None)
            if user_id is not None:
                await auth_store.add_member(
                    session, project_id=rec.id, user_id=user_id, role="owner"
                )
        else:
            rec.name = sig.name
            rec.local_path = str(alvo)

        await session.flush()

    # ADR 0016: `resolve()` (workspace/projects.py) é o que faz arquivo,
    # agente, índice, LSP, packages, git etc. encontrarem este projeto — sem
    # isto, ele só resolveria depois de alguém abrir `GET /api/projects`
    # (que rehidrata o cache) ou reiniciar a API.
    register_local_path(slug, str(alvo))

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="open_path",
                details=f"Pasta aberta como projeto: {alvo}",
                metadata={"slug": slug, "path": str(alvo)},
                project_slug=slug,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {
        "slug": slug,
        "name": sig.name,
        "path": sig.path,
        "primary_language": sig.primary_language,
        "frameworks": sig.frameworks,
        "build_system": sig.build_system,
        "has_docker": sig.has_docker,
        "has_git": sig.has_git,
        "has_ci_cd": sig.has_ci_cd,
        "summary": sig.executive_summary,
    }


@router.post("/inspect-path", dependencies=[AdminDep])
async def inspect_path(payload: InspectPathIn, request: Request) -> dict[str, Any]:
    """Inspeciona metadados, stack e resumo executivo de qualquer pasta antes
    de vincular. Restrita a `AdminDep`: lê arquivos (`package.json`,
    manifestos etc.) de qualquer diretório do host que o admin apontar, o
    mesmo raio de alcance de `/open-path` — ver o comentário lá."""
    from eltanix.workspace.inspector import ProjectInspector

    projects_root = _projects_root(request)
    alvo = await asyncio.to_thread(lambda: _resolve_user_path(payload.path, projects_root))
    if not alvo.exists() or not alvo.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho não encontrado ou não é diretório: {payload.path}",
        )

    inspector = ProjectInspector()
    sig = inspector.inspect(alvo)
    return {
        "name": sig.name,
        "path": sig.path,
        "primary_language": sig.primary_language,
        "frameworks": sig.frameworks,
        "build_system": sig.build_system,
        "has_docker": sig.has_docker,
        "has_git": sig.has_git,
        "has_ci_cd": sig.has_ci_cd,
        "summary": sig.executive_summary,
    }


@router.post("/filesystem/browse", dependencies=[AdminDep])
async def browse_filesystem(payload: BrowsePathIn, request: Request) -> dict[str, Any]:
    """Lista pastas e raízes do sistema de arquivos para o explorador visual
    de projetos. Restrita a `AdminDep`: `_list_system_roots` devolve de
    propósito TODA letra de drive (Windows) ou `/` (Unix), e a listagem em si
    enumera o conteúdo de qualquer diretório do host — uma sessão comum não
    deveria conseguir varrer o disco inteiro pela IDE."""
    projects_root = _projects_root(request)
    roots = _list_system_roots(projects_root)

    # Se nenhum caminho foi informado, inicia explorando a Raiz de Projetos
    raw_path = payload.path.strip() if payload.path and payload.path.strip() else str(projects_root)
    alvo = await asyncio.to_thread(lambda: _resolve_user_path(raw_path, projects_root))

    if not alvo.exists() or not alvo.is_dir():
        alvo = projects_root if projects_root.exists() else Path.home()

    breadcrumbs: list[dict[str, str]] = []
    curr = alvo
    while curr != curr.parent:
        breadcrumbs.append({"name": curr.name or str(curr), "path": str(curr)})
        curr = curr.parent
    breadcrumbs.append({"name": curr.name or str(curr), "path": str(curr)})
    breadcrumbs.reverse()

    parent_path = str(alvo.parent) if alvo.parent != alvo else None

    ignorar = {
        "$RECYCLE.BIN",
        "System Volume Information",
        "node_modules",
        ".git",
        ".venv",
        "__pycache__",
        ".eltanix",
        ".next",
        "dist",
        "build",
    }

    def _scan() -> list[dict[str, Any]]:
        res = []
        for item in sorted(alvo.iterdir(), key=lambda p: p.name.lower()):
            try:
                if item.is_dir() and item.name not in ignorar and not item.name.startswith("."):
                    has_git = (item / ".git").exists()
                    has_pkg = (item / "package.json").exists()
                    has_py = (item / "pyproject.toml").exists() or (item / "requirements.txt").exists()
                    res.append({
                        "name": item.name,
                        "path": str(item),
                        "has_git": has_git,
                        "is_project": bool(has_git or has_pkg or has_py),
                    })
            except (PermissionError, OSError):
                continue
        return res

    try:
        dirs = await asyncio.to_thread(_scan)
    except (PermissionError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sem permissão para ler o diretório: {exc}",
        ) from exc

    return {
        "current_path": str(alvo),
        "parent_path": parent_path,
        "breadcrumbs": breadcrumbs,
        "roots": roots,
        "directories": dirs[:120],
        # Sem isto o cliente não tinha como saber que a lista foi cortada —
        # uma pasta com mais de 120 subpastas escondia o resto em silêncio.
        "truncated": len(dirs) > 120,
        "total_directories": len(dirs),
    }



@router.get("/{slug}/summary")
async def get_summary(slug: str, request: Request) -> dict[str, Any]:
    """Retorna a visão geral 360° do projeto (IDE, Git, Custos, Notas, Graphify, etc.)."""
    # Fora do `try/except Exception` logo abaixo de propósito: esse bloco tem
    # fallback para leitura direta em disco quando o Postgres está fora do ar,
    # e um `except Exception` genérico ali engoliria o 403 do RBAC junto.
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="viewer")

    projects_root = _projects_root(request)
    try:
        async with session_scope() as session:
            summary = await get_project_summary(session, slug, projects_root)
            return {
                "slug": summary.slug,
                "name": summary.name,
                "description": summary.description,
                "local_path": summary.local_path,
                "git_url": summary.git_url,
                "is_git": summary.is_git,
                "branch": summary.branch,
                "budget_limit_usd": summary.budget_limit_usd,
                "total_cost_usd": summary.total_cost_usd,
                "total_tokens": summary.total_tokens,
                "notes_count": summary.notes_count,
                "documents_count": summary.documents_count,
                "graph_nodes_count": summary.graph_nodes_count,
                "graph_edges_count": summary.graph_edges_count,
                "audit_events_count": summary.audit_events_count,
                "active_sessions_count": summary.active_sessions_count,
                "recent_commits": summary.recent_commits,
                "settings": summary.settings,
            }
    except Exception as exc:
        log.warning("projects.summary.fallback", slug=slug, error=str(exc))
        try:
            target_path = resolve(projects_root, slug)
            is_git = (target_path / ".git").exists()
            branch = _branch_of(target_path) if is_git else None
            return {
                "slug": target_path.name,
                "name": target_path.name,
                "description": f"Projeto local em {target_path.name}",
                "local_path": str(target_path),
                "git_url": None,
                "is_git": is_git,
                "branch": branch,
                "budget_limit_usd": None,
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "notes_count": 0,
                "documents_count": 0,
                "graph_nodes_count": 0,
                "graph_edges_count": 0,
                "audit_events_count": 0,
                "active_sessions_count": 0,
                "recent_commits": [],
                "settings": {},
            }
        except ProjectError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err


@router.patch("/{slug}")
async def update_project(slug: str, payload: ProjectUpdateIn, request: Request) -> dict[str, Any]:
    """Atualiza metadados e limites do projeto."""
    try:
        slug_valido = validate_name(slug)
    except ProjectError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug_valido, min_role="editor")
        stmt = select(ProjectRecord).where(ProjectRecord.slug == slug_valido)
        rec = (await session.execute(stmt)).scalar_one_or_none()
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Projeto {slug} não encontrado."
            )

        # `model_fields_set` (Pydantic v2) distingue "campo ausente do JSON"
        # de "campo mandado como `null`" — o `is not None` de antes tratava
        # os dois igual, então não havia como limpar `git_url`/
        # `budget_limit_usd` (colunas anuláveis) de volta pra `null` num PATCH
        # parcial: mandar `{"git_url": null}` simplesmente não fazia nada.
        campos = payload.model_fields_set

        if "name" in campos:
            if payload.name is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="`name` não pode ser nulo — a coluna não aceita.",
                )
            rec.name = payload.name
        if "description" in campos:
            # Coluna NOT NULL com default `""` — `null` no payload limpa pra
            # vazio, igual o default, em vez de rejeitar.
            rec.description = payload.description or ""
        if "git_url" in campos:
            rec.git_url = payload.git_url
        if "budget_limit_usd" in campos:
            rec.budget_limit_usd = payload.budget_limit_usd
        if "settings" in campos:
            if payload.settings is None:
                rec.settings = {}
            else:
                # MERGE raso, não substituição: um PATCH mandando só uma
                # chave nova não pode apagar as outras que já existiam. Uma
                # chave explicitamente `null` dentro de `settings` remove
                # só ela — a única forma de apagar uma chave sem reescrever
                # o dict inteiro.
                merged = dict(rec.settings or {})
                for chave, valor in payload.settings.items():
                    if valor is None:
                        merged.pop(chave, None)
                    else:
                        merged[chave] = valor
                rec.settings = merged

        await session.flush()
        await session.refresh(rec)

        budget_limit = float(rec.budget_limit_usd) if rec.budget_limit_usd is not None else None
        res = {
            "slug": rec.slug,
            "name": rec.name,
            "description": rec.description,
            "git_url": rec.git_url,
            "budget_limit_usd": budget_limit,
            "settings": rec.settings,
        }

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="update",
                details=f"Projeto atualizado: {slug_valido}",
                metadata={"slug": slug_valido},
                project_slug=slug_valido,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return res


@router.delete("/{slug}")
async def delete_project(slug: str, request: Request, delete_files: bool = False) -> dict[str, Any]:
    """Remove o registro do projeto no banco de dados (e opcionalmente no disco)."""
    try:
        slug_valido = validate_name(slug)
    except ProjectError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    projects_root = _projects_root(request)

    # Resolvido ANTES de apagar o registro/cache abaixo — depois disso
    # `resolve()` não teria mais como achar um projeto vinculado fora de
    # PROJECTS_ROOT (ADR 0016, `register_local_path`).
    target_path: Path | None = None
    if delete_files:
        try:
            target_path = resolve(projects_root, slug_valido)
        except ProjectError:
            target_path = None  # nada no disco sob esse slug — segue sem erro

    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug_valido, min_role="owner")
        rec = (
            await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug_valido))
        ).scalar_one_or_none()
        if rec:
            await session.delete(rec)

    # Fora do `if delete_files` de propósito: sem isto, um slug reaproveitado
    # por `create_project` logo depois herdaria o `local_path` do projeto já
    # apagado, até o próximo restart/rehidratação (ADR 0016).
    register_local_path(slug_valido, None)

    files_deleted = False
    delete_error: str | None = None
    if delete_files and target_path is not None:
        try:
            shutil.rmtree(target_path)
            files_deleted = True
        except FileNotFoundError:
            files_deleted = True  # já não existia — mesmo resultado do ponto de vista do pedido
        except OSError as exc:
            # Antes era `ignore_errors=True`: um arquivo travado por outro
            # processo, ou uma permissão faltando, virava silenciosamente
            # "apagado com sucesso" sem nada ter sido apagado.
            delete_error = str(exc)
            log.warning("projects.delete.rmtree_failed", slug=slug_valido, error=delete_error)

    if audit := _audit(request):
        try:
            detail_extra = f", erro={delete_error}" if delete_error else ""
            await audit.record(
                actor="user",
                module="projects",
                action="delete",
                details=(
                    f"Projeto removido: {slug_valido} "
                    f"(arquivos_apagados={files_deleted}{detail_extra})"
                ),
                metadata={
                    "slug": slug_valido,
                    "delete_files": delete_files,
                    "files_deleted": files_deleted,
                },
                project_slug=slug_valido,
                risk_level="critical" if delete_files else "medium",
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {
        "status": "ok",
        "slug": slug_valido,
        "files_deleted": files_deleted,
        # Presente só quando `delete_files=True` e o rmtree falhou de verdade
        # — o cadastro já foi removido de qualquer forma (ver acima).
        "delete_error": delete_error,
    }


@router.post("/{slug}/prewarm")
async def prewarm_project(slug: str, request: Request) -> dict[str, Any]:
    """Pré-aquece o sandbox e o ecossistema do projeto (ambiente, container e Playwright)."""
    projects_root = _projects_root(request)
    try:
        slug_valido = validate_name(slug)
        workspace_root = resolve(projects_root, slug_valido)
    except ProjectError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    async with session_scope() as session:
        # `viewer` era o mínimo antes — permite mudar de papel só de olhar um
        # projeto: cria/reaproveita sessão de agente e sobe container de
        # sandbox, o mesmo raio de alcance de operações que em outro lugar
        # exigem `editor`.
        await require_role_by_slug(session, request, project_slug=slug_valido, min_role="editor")

    # 1. Garante o ambiente de pacotes do projeto (.venv, etc.)
    try:
        from eltanix.api.routes.packages import ensure_project_env

        await ensure_project_env(workspace_root)
    except Exception as exc:
        log.warning("projects.prewarm.env_failed", slug=slug_valido, error=str(exc))

    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return {"status": "ok", "slug": slug_valido, "sandbox_ready": False}

    # 2. Reutiliza ou cria uma sessão pré-aquecida para a IDE
    sessao_ativa = runner.find_session_for_workspace(workspace_root)

    if sessao_ativa is None:
        try:
            sessao_ativa = await runner.create_session(
                task="Sessão Pré-aquecida da IDE",
                workspace_root=workspace_root,
                mode="auto",
            )
        except Exception as exc:
            log.warning("projects.prewarm.session_failed", slug=slug_valido, error=str(exc))

    is_web = getattr(sessao_ativa, "is_web_app", False) if sessao_ativa else False
    web_prewarmed = getattr(sessao_ativa, "web_prewarmed", False) if sessao_ativa else False
    session_id = sessao_ativa.session_id if sessao_ativa else None

    if sessao_ativa and is_web and not web_prewarmed:
        try:
            web_prewarmed = await runner.prewarm_web_app(sessao_ativa.session_id, force=True)
        except Exception as exc:
            log.warning("projects.prewarm.web_failed", session=session_id, error=str(exc))

    return {
        "status": "ok",
        "slug": slug_valido,
        "session_id": session_id,
        "sandbox_ready": bool(sessao_ativa and sessao_ativa.sandbox_available),
        "is_web_app": is_web,
        "web_prewarmed": web_prewarmed,
    }


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: str = Field(default="viewer", description="viewer, editor ou owner")


async def _get_project_record_or_404(session: AsyncSession, slug: str) -> ProjectRecord:
    stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
    rec = (await session.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Projeto {slug} não encontrado."
        )
    return rec


async def _is_last_owner(
    session: AsyncSession, *, project_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """`True` se `user_id` é `owner` do projeto e ninguém mais é — usado para
    bloquear remover ou rebaixar o último dono. Sem isto, um `owner` sozinho
    podia se auto-remover (ou ser rebaixado) e deixar o projeto sem nenhum
    `owner`, recuperável só pelo admin da instância (`AdminDep` bypassa RBAC
    por projeto, mas ninguém deveria precisar disso pra uma operação normal
    de gestão de membro)."""
    membros = await auth_store.list_members(session, project_id=project_id)
    atual = next((m for m in membros if m.user_id == user_id), None)
    if atual is None or atual.role != "owner":
        return False
    outros_owners = [m for m in membros if m.role == "owner" and m.user_id != user_id]
    return not outros_owners


@router.get("/{slug}/members")
async def list_members(slug: str, request: Request) -> dict[str, Any]:
    from eltanix.db.models import AppUser

    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="viewer")
        rec = await _get_project_record_or_404(session, slug)
        members = await auth_store.list_members(session, project_id=rec.id)
        # `ProjectMember` só guarda `user_id` — a UI (aba "Membros" do Hub
        # 360°) precisa de `username`/`display_name` pra listar gente por
        # nome, não por UUID cru.
        usuarios: dict[uuid.UUID, AppUser] = {}
        if members:
            stmt_users = select(AppUser).where(AppUser.id.in_({m.user_id for m in members}))
            usuarios = {u.id: u for u in (await session.execute(stmt_users)).scalars()}
        return {
            "members": [
                {
                    "user_id": str(m.user_id),
                    "username": usuarios[m.user_id].username if m.user_id in usuarios else None,
                    "display_name": usuarios[m.user_id].display_name if m.user_id in usuarios else None,
                    "role": m.role,
                    "created_at": m.created_at.isoformat(),
                }
                for m in members
            ]
        }


@router.post("/{slug}/members")
async def add_member(slug: str, payload: MemberIn, request: Request) -> dict[str, Any]:
    """Convite/mudança de papel — só `owner` do projeto (ou admin da instância)
    gerencia quem mais tem acesso, mesma fronteira de `delete_project`."""
    if payload.role not in ROLE_RANK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Papel inválido: {payload.role!r}"
        )
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="owner")
        rec = await _get_project_record_or_404(session, slug)
        if payload.role != "owner" and await _is_last_owner(
            session, project_id=rec.id, user_id=payload.user_id
        ):
            # `add_member` é upsert: rebaixar o único `owner` pra
            # `editor`/`viewer` orfana o projeto do mesmo jeito que removê-lo
            # — mesmo guard de `remove_member` abaixo.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Este usuário é o único owner do projeto — promova outro membro a "
                    "owner antes de rebaixá-lo."
                ),
            )
        member = await auth_store.add_member(
            session, project_id=rec.id, user_id=payload.user_id, role=payload.role
        )

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="member_add",
                details=f"{payload.user_id} -> {payload.role}",
                metadata={"slug": slug, "user_id": str(payload.user_id), "role": payload.role},
                project_slug=slug,
                risk_level="medium",
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {"user_id": str(member.user_id), "role": member.role}


@router.delete("/{slug}/members/{user_id}")
async def remove_member(slug: str, user_id: uuid.UUID, request: Request) -> dict[str, Any]:
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="owner")
        rec = await _get_project_record_or_404(session, slug)
        if await _is_last_owner(session, project_id=rec.id, user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Este usuário é o único owner do projeto — promova outro membro a "
                    "owner antes de removê-lo."
                ),
            )
        removed = await auth_store.remove_member(session, project_id=rec.id, user_id=user_id)

    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro não encontrado.")

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="member_remove",
                details=str(user_id),
                metadata={"slug": slug, "user_id": str(user_id)},
                project_slug=slug,
                risk_level="medium",
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {"removed": True}
