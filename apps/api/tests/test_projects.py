"""Testes unitários e de integração para a arquitetura de projetos."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import Request

from eltanix.agent.tools import RiskClass, ToolContext, registry
from eltanix.workspace.projects import (
    list_projects,
    sync_projects_db,
    validate_name,
)


def test_validate_name():
    assert validate_name("meu-projeto") == "meu-projeto"
    with pytest.raises(ValueError):
        validate_name("../hack")
    with pytest.raises(ValueError):
        validate_name("projeto/sub")


def test_resolve_case_insensitive(tmp_path: Path):
    from eltanix.workspace.projects import resolve
    (tmp_path / "Mestrado").mkdir()
    res = resolve(tmp_path, "mestrado")
    assert res.name == "Mestrado"


def test_list_projects(tmp_path: Path):
    (tmp_path / "proj1").mkdir()
    (tmp_path / "proj2").mkdir()
    (tmp_path / ".git").mkdir()

    projs = list_projects(tmp_path)
    slugs = {p.slug for p in projs}
    assert "proj1" in slugs
    assert "proj2" in slugs
    assert ".git" not in slugs


def test_manage_project_tool_registered():
    tool = registry.get("manage_project")
    assert tool is not None
    assert tool.risk is RiskClass.READ


@pytest.mark.asyncio
async def test_manage_project_tool_action_list(tmp_path: Path):
    (tmp_path / "demo").mkdir()

    ctx = MagicMock(spec=ToolContext)
    ctx.projects_root = tmp_path
    ctx.project = "demo"

    tool = registry.get("manage_project")
    assert tool is not None

    res = await tool.handler(ctx, {"action": "list"})
    assert res.ok
    assert "demo" in str(res.data)


@pytest.mark.asyncio
async def test_sync_projects_db_with_postgres(pg_session, tmp_path: Path):
    (tmp_path / "proj_db").mkdir()
    records = await sync_projects_db(pg_session, tmp_path)
    assert any(r.slug == "proj_db" for r in records)


@pytest.mark.asyncio
async def test_sync_projects_db_assigns_admin_as_owner(pg_session, tmp_path: Path):
    """ADR 0016, Fase 3: pasta nova descoberta em disco ganha o admin da
    instância como `owner` na hora do cadastro automático — sem isso, RBAC
    deixaria o projeto invisível pra qualquer usuário comum (só admin/canal
    de serviço enxergam projeto sem `ProjectMember`, ver `list_projects`)
    até alguém convidar manualmente."""
    import uuid

    from eltanix.auth import store as auth_store
    from eltanix.auth.service import _hash_password
    from eltanix.db.models import AppUser

    admin = AppUser(
        username=f"admin-{uuid.uuid4().hex[:8]}",
        password_hash=_hash_password("x"),
        is_admin=True,
    )
    pg_session.add(admin)
    await pg_session.flush()

    (tmp_path / "proj_com_dono").mkdir()
    records = await sync_projects_db(pg_session, tmp_path)
    rec = next(r for r in records if r.slug == "proj_com_dono")

    membros = await auth_store.list_members(pg_session, project_id=rec.id)
    assert len(membros) == 1
    assert membros[0].user_id == admin.id
    assert membros[0].role == "owner"

    # Rodar de novo (o polling da Central de Projetos faz isso o tempo todo)
    # não deve duplicar o `ProjectMember` pra um slug já cadastrado.
    await sync_projects_db(pg_session, tmp_path)
    membros_de_novo = await auth_store.list_members(pg_session, project_id=rec.id)
    assert len(membros_de_novo) == 1


@pytest.mark.asyncio
async def test_audit_service_record_accepts_event_metadata_alias(pg_session):
    from eltanix.audit.service import AuditService
    service = AuditService()
    entry = await service.record(
        actor="test",
        module="test",
        action="test_action",
        event_metadata={"key": "val"},
    )
    assert entry.event_metadata == {"key": "val"}


@pytest.mark.asyncio
async def test_create_project_endpoint(tmp_path: Path):
    """Exercita a rota via HTTP de verdade — `create_project` usa
    `session_scope()` internamente (não uma sessão injetável), então só roda
    com `DATABASE_URL_TEST` (mesmo padrão de `pg_session`, ver
    `apps/api/CLAUDE.md`). Sem isso, é `test_create_project_fails_fast_without_db`
    logo abaixo que cobre o caminho sem banco."""
    import os

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from eltanix.api.deps import require_session
    from eltanix.db.models import ProjectRecord
    from eltanix.db.session import init_engine, session_scope, shutdown_engine
    from eltanix.main import create_app

    init_engine(url)
    try:
        app = create_app()
        app.state.projects_root = tmp_path
        app.dependency_overrides[require_session] = lambda: None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/projects",
                json={"name": "Sorteador", "description": "Criar um sorteador para utilizar em aulas"},
            )
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["name"] == "Sorteador"
            # `slugify()` normaliza para kebab-case minúsculo (ADR 0016).
            assert data["slug"] == "sorteador"
            assert (tmp_path / "sorteador").is_dir()
    finally:
        # `session_scope()` comita de verdade (ao contrário do `pg_session`
        # de rollback-only) — sem isto, "sorteador" fica pra sempre gravado
        # em DATABASE_URL_TEST.
        async with session_scope() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.slug == "sorteador")
            rec = (await session.execute(stmt)).scalar_one_or_none()
            if rec:
                await session.delete(rec)
        await shutdown_engine()


@pytest.mark.asyncio
async def test_create_project_fails_fast_without_db(tmp_path: Path):
    """Sem Postgres alcançável, `create_project` falha com 503 ANTES de criar
    a pasta em disco — não mais um 200 fabricado (o comportamento antigo:
    ver o commit que introduziu este teste, `docs/adr/0016-...`). Roda sem
    `DATABASE_URL_TEST` de propósito: é exatamente a ausência de engine que
    este teste verifica."""
    from httpx import ASGITransport, AsyncClient

    from eltanix.api.deps import require_session
    from eltanix.main import create_app

    app = create_app()
    app.state.projects_root = tmp_path
    app.dependency_overrides[require_session] = lambda: None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/projects",
            json={"name": "SemBanco", "description": "não deveria criar nada"},
        )
        assert res.status_code == 503, res.text

    # A checagem de permissão/existência (que detecta o banco fora) acontece
    # ANTES do `mkdir` — nenhum artefato deveria ter sido criado em disco.
    assert not (tmp_path / "SemBanco").exists()


@pytest.mark.asyncio
async def test_inspect_and_browse_filesystem_endpoints(tmp_path: Path):
    from httpx import ASGITransport, AsyncClient
    from eltanix.api.deps import require_admin, require_session
    from eltanix.main import create_app

    app = create_app()
    app.state.projects_root = tmp_path
    app.dependency_overrides[require_session] = lambda: None
    # `/inspect-path` e `/filesystem/browse` são restritas a `AdminDep`
    # (enumeram/leem qualquer diretório do host) — sem este override, o teste
    # bateria 403 em vez de exercitar o comportamento das rotas.
    app.dependency_overrides[require_admin] = lambda: None

    # Cria pasta de exemplo com package.json
    demo_dir = tmp_path / "meu-app-react"
    demo_dir.mkdir()
    (demo_dir / "package.json").write_text('{"dependencies": {"react": "^18.0.0", "next": "^14.0.0"}}', encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Teste de inspeção
        res_inspect = await ac.post("/api/projects/inspect-path", json={"path": str(demo_dir)})
        assert res_inspect.status_code == 200, res_inspect.text
        data_inspect = res_inspect.json()
        assert data_inspect["name"] == "meu-app-react"
        assert "React" in data_inspect["frameworks"]
        assert "Next.js" in data_inspect["frameworks"]

        # 2. Teste de navegação do sistema de arquivos
        res_browse = await ac.post("/api/projects/filesystem/browse", json={"path": str(tmp_path)})
        assert res_browse.status_code == 200, res_browse.text
        data_browse = res_browse.json()
        assert data_browse["current_path"] == str(tmp_path.resolve())
        assert any(d["name"] == "meu-app-react" for d in data_browse["directories"])

        # 3. Teste de listagem de raízes quando path é vazio
        res_roots = await ac.post("/api/projects/filesystem/browse", json={"path": None})
        assert res_roots.status_code == 200, res_roots.text
        data_roots = res_roots.json()
        assert len(data_roots["roots"]) > 0


def test_resolve_uses_registered_local_path_outside_root(tmp_path: Path):
    """ADR 0016: `register_local_path` (chamado por `open-path`/`delete`) faz
    `resolve()` — usado por arquivo, agente, índice, LSP, packages, git...,
    todos síncronos e sem sessão de banco — encontrar um projeto vinculado
    fora de PROJECTS_ROOT. Sem passar pela rota HTTP (que precisa de Postgres
    de verdade pra gravar o `ProjectRecord`) — o que importa aqui é só a
    leitura do cache em memória que a rota popula."""
    from eltanix.workspace.path_guard import default_path_guard
    from eltanix.workspace.projects import register_local_path, resolve

    projects_root = tmp_path / "root"
    projects_root.mkdir()
    external = tmp_path / "fora-da-raiz" / "MeuProjetoExterno"
    external.mkdir(parents=True)

    slug = "MeuProjetoExterno"
    default_path_guard.allow(external)
    register_local_path(slug, str(external))
    try:
        assert resolve(projects_root, slug) == external.resolve()

        # Evicção (o que `delete_project` faz): sem `local_path` registrado e
        # sem homônimo sob `projects_root`, volta a "não encontrado".
        register_local_path(slug, None)
        with pytest.raises(ValueError):  # ProjectError, subclasse de ValueError
            resolve(projects_root, slug)
    finally:
        register_local_path(slug, None)


def test_reject_filesystem_root_blocks_drive_and_home():
    from eltanix.api.routes.projects import _reject_filesystem_root
    from fastapi import HTTPException

    # Raiz de filesystem: `alvo.parent == alvo` é verdade tanto pra "/" quanto
    # pra "C:\\" no Windows — usa `Path("/").resolve()` que cai numa raiz em
    # qualquer SO onde o teste rodar.
    root = Path("/").resolve()
    with pytest.raises(HTTPException) as exc_info:
        _reject_filesystem_root(root)
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException):
        _reject_filesystem_root(Path.home().resolve())


@pytest.mark.asyncio
async def test_find_orphaned_project_data(pg_session):
    """ADR 0016 / find_orphaned_project_data: detecta dado órfão por slug
    (Note) e por workspace (IndexedFile) — as duas convenções que coexistem
    no schema (graphify usa slug em `workspace`; context/indexer.py usa
    caminho absoluto)."""
    import uuid

    from eltanix.db.models import IndexedFile, Note
    from eltanix.workspace.projects import find_orphaned_project_data

    slug = f"orfao-{uuid.uuid4().hex[:8]}"
    pg_session.add(Note(project_slug=slug, title="nota órfã", content="..."))
    pg_session.add(
        IndexedFile(
            workspace="/tmp/workspace-orfao",
            path="a.py",
            language="python",
            content_hash="deadbeef",
        )
    )
    await pg_session.flush()

    achados_slug = await find_orphaned_project_data(pg_session, slug=slug)
    assert "notas (Segundo Cérebro)" in achados_slug

    achados_workspace = await find_orphaned_project_data(
        pg_session, slug="slug-sem-nada", workspace_path="/tmp/workspace-orfao"
    )
    assert "índice semântico de código" in achados_workspace

    achados_vazio = await find_orphaned_project_data(
        pg_session, slug="slug-totalmente-limpo", workspace_path="/tmp/nada-aqui"
    )
    assert achados_vazio == []


@pytest.mark.asyncio
async def test_create_project_blocks_slug_with_orphaned_data(tmp_path: Path):
    """ADR 0016: `create_project` recusa (409) reaproveitar um slug que ainda
    tem dado órfão de um projeto apagado, e NÃO cria a pasta em disco."""
    import os

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from eltanix.api.deps import require_session
    from eltanix.db.models import Note
    from eltanix.db.session import init_engine, session_scope, shutdown_engine
    from eltanix.main import create_app
    from eltanix.workspace.projects import slugify

    nome = "OrfaoTeste"
    # `create_project` calcula e checa órfãos pelo slug kebab-case
    # (`slugify(nome)`), não pelo nome cru — o dado órfão precisa estar
    # gravado sob essa mesma chave para o bloqueio disparar.
    slug = slugify(nome)
    init_engine(url)
    try:
        async with session_scope() as session:
            session.add(Note(project_slug=slug, title="resquício", content="..."))

        app = create_app()
        app.state.projects_root = tmp_path
        app.dependency_overrides[require_session] = lambda: None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post("/api/projects", json={"name": nome})
            assert res.status_code == 409, res.text

        assert not (tmp_path / slug).exists()
        assert not (tmp_path / nome).exists()
    finally:
        async with session_scope() as session:
            stmt = select(Note).where(Note.project_slug == slug)
            for nota in (await session.execute(stmt)).scalars().all():
                await session.delete(nota)
        await shutdown_engine()


@pytest.mark.asyncio
async def test_list_members_endpoint_includes_username(tmp_path: Path):
    """ADR 0016, Fase 3: `GET /{slug}/members` enriquece `ProjectMember`
    (só `user_id`) com `username`/`display_name` de `AppUser` — a aba
    "Membros" do Hub 360° lista gente pelo nome, não por UUID cru."""
    import os
    import uuid

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from eltanix.api.deps import require_session
    from eltanix.auth.service import _hash_password
    from eltanix.db.models import AppUser, ProjectMember, ProjectRecord
    from eltanix.db.session import init_engine, session_scope, shutdown_engine
    from eltanix.main import create_app

    slug = f"proj-membros-{uuid.uuid4().hex[:8]}"
    username = f"membro-{uuid.uuid4().hex[:8]}"
    init_engine(url)
    try:
        async with session_scope() as session:
            rec = ProjectRecord(slug=slug, name="Projeto de Membros", local_path=str(tmp_path), default_branch="main")
            user = AppUser(username=username, password_hash=_hash_password("x"), display_name="Membro Teste")
            session.add_all([rec, user])
            await session.flush()
            session.add(ProjectMember(project_id=rec.id, user_id=user.id, role="editor"))

        app = create_app()

        async def _fake_session(request: Request) -> None:
            # `require_role_by_slug` lê `request.state.is_service` — sem
            # `require_session` de verdade rodando, essas flags nunca são
            # setadas; imita o canal de serviço (mesmo bypass de RBAC que
            # `AuthDep` concede pra uma API key válida).
            request.state.is_service = True
            request.state.user_id = None
            request.state.is_admin = False

        app.dependency_overrides[require_session] = _fake_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.get(f"/api/projects/{slug}/members")
            assert res.status_code == 200, res.text
            membros = res.json()["members"]
            assert len(membros) == 1
            assert membros[0]["username"] == username
            assert membros[0]["display_name"] == "Membro Teste"
            assert membros[0]["role"] == "editor"
    finally:
        async with session_scope() as session:
            rec = (await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug))).scalar_one_or_none()
            if rec:
                await session.delete(rec)
            user = (await session.execute(select(AppUser).where(AppUser.username == username))).scalar_one_or_none()
            if user:
                await session.delete(user)
        await shutdown_engine()


@pytest.mark.asyncio
async def test_create_project_clone_blocks_ssrf_and_bad_scheme(tmp_path: Path):
    """ADR 0016, Fase 4: `clone: true` reusa `validate_target_url` (ADR 0006)
    — bloqueia metadados de nuvem/rede interna e exige http(s) (sem
    `ssh://`), e não deixa pasta órfã em disco quando recusa."""
    import os

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient

    from eltanix.api.deps import require_session
    from eltanix.db.session import init_engine, shutdown_engine
    from eltanix.main import create_app

    init_engine(url)
    try:
        app = create_app()
        app.state.projects_root = tmp_path
        app.dependency_overrides[require_session] = lambda: None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/projects",
                json={
                    "name": "ClonagemSSRF",
                    "git_url": "http://169.254.169.254/latest/meta-data",
                    "clone": True,
                },
            )
            assert res.status_code == 400, res.text
            assert not (tmp_path / "clonagemssrf").exists()

            res2 = await ac.post(
                "/api/projects",
                json={"name": "ClonagemSSH", "git_url": "ssh://git@github.com/x/y.git", "clone": True},
            )
            assert res2.status_code == 400, res2.text
            assert not (tmp_path / "clonagemssh").exists()
    finally:
        await shutdown_engine()


@pytest.mark.asyncio
async def test_create_project_clone_success_creates_record(tmp_path: Path, monkeypatch):
    """`clone: true` chama `Repo.clone_from` de verdade — mockado aqui (sem
    rede) só pra confirmar que o resultado (pasta com o conteúdo "clonado" +
    `ProjectRecord` persistido com o `git_url` limpo, sem o token embutido)
    segue o caminho de sucesso, e não o de `git init` numa pasta vazia que
    esta rota fazia antes."""
    import os

    import git

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from eltanix.api.deps import require_session
    from eltanix.db.models import ProjectRecord
    from eltanix.db.session import init_engine, session_scope, shutdown_engine
    from eltanix.main import create_app

    def _fake_clone(clone_url: str, to_path, *args, **kwargs):
        # O token (se veio) só deve existir nesta URL efêmera passada pro
        # `git clone` — nunca no `git_url` persistido/devolvido (checado
        # abaixo, na resposta HTTP).
        assert "supertoken123" in clone_url
        Path(to_path).mkdir(parents=True, exist_ok=True)
        (Path(to_path) / "README.md").write_text("conteúdo clonado", encoding="utf-8")
        return MagicMock()

    monkeypatch.setattr(git.Repo, "clone_from", staticmethod(_fake_clone))

    init_engine(url)
    slug: str | None = None
    try:
        app = create_app()
        app.state.projects_root = tmp_path
        app.dependency_overrides[require_session] = lambda: None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/projects",
                json={
                    "name": "RepoClonadoDeVerdade",
                    "git_url": "https://github.com/exemplo/privado.git",
                    "clone": True,
                    "git_token": "supertoken123",
                },
            )
            assert res.status_code == 200, res.text
            data = res.json()
            slug = data["slug"]
            assert data["git_url"] == "https://github.com/exemplo/privado.git"
            assert (tmp_path / slug / "README.md").is_file()
    finally:
        if slug:
            async with session_scope() as session:
                rec = (
                    await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug))
                ).scalar_one_or_none()
                if rec:
                    await session.delete(rec)
        await shutdown_engine()


@pytest.mark.asyncio
async def test_last_owner_guard_blocks_demote_and_remove(tmp_path: Path):
    """`_is_last_owner` (`api/routes/projects.py`) impede que o único `owner`
    de um projeto seja rebaixado ou removido — sem isso, um projeto ficava
    sem nenhum `owner`, recuperável só via `AdminDep`. Cobre os dois pontos
    onde a guarda é chamada: `POST /{slug}/members` (upsert que rebaixaria) e
    `DELETE /{slug}/members/{user_id}`."""
    import os
    import uuid

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from eltanix.api.deps import require_session
    from eltanix.auth.service import _hash_password
    from eltanix.db.models import AppUser, ProjectMember, ProjectRecord
    from eltanix.db.session import init_engine, session_scope, shutdown_engine
    from eltanix.main import create_app

    slug = f"proj-last-owner-{uuid.uuid4().hex[:8]}"
    username_a = f"owner-a-{uuid.uuid4().hex[:8]}"
    username_b = f"owner-b-{uuid.uuid4().hex[:8]}"
    init_engine(url)
    try:
        async with session_scope() as session:
            rec = ProjectRecord(slug=slug, name="Projeto Last Owner", local_path=str(tmp_path), default_branch="main")
            user_a = AppUser(username=username_a, password_hash=_hash_password("x"))
            user_b = AppUser(username=username_b, password_hash=_hash_password("x"))
            session.add_all([rec, user_a, user_b])
            await session.flush()
            session.add(ProjectMember(project_id=rec.id, user_id=user_a.id, role="owner"))
            project_id, user_a_id, user_b_id = rec.id, user_a.id, user_b.id

        app = create_app()

        async def _fake_session(request: Request) -> None:
            request.state.is_service = True
            request.state.user_id = None
            request.state.is_admin = False

        app.dependency_overrides[require_session] = _fake_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Rebaixar o único owner: bloqueado.
            res_demote = await ac.post(
                f"/api/projects/{slug}/members", json={"user_id": str(user_a_id), "role": "viewer"}
            )
            assert res_demote.status_code == 409, res_demote.text

            # Remover o único owner: bloqueado.
            res_remove = await ac.delete(f"/api/projects/{slug}/members/{user_a_id}")
            assert res_remove.status_code == 409, res_remove.text

            # Com um segundo owner, as duas operações passam a valer.
            res_add_b = await ac.post(
                f"/api/projects/{slug}/members", json={"user_id": str(user_b_id), "role": "owner"}
            )
            assert res_add_b.status_code == 200, res_add_b.text

            res_demote_ok = await ac.post(
                f"/api/projects/{slug}/members", json={"user_id": str(user_a_id), "role": "viewer"}
            )
            assert res_demote_ok.status_code == 200, res_demote_ok.text
    finally:
        async with session_scope() as session:
            rec = (await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug))).scalar_one_or_none()
            if rec:
                await session.delete(rec)
            for username in (username_a, username_b):
                user = (await session.execute(select(AppUser).where(AppUser.username == username))).scalar_one_or_none()
                if user:
                    await session.delete(user)
        await shutdown_engine()


@pytest.mark.asyncio
async def test_delete_project_with_and_without_delete_files(tmp_path: Path):
    """`DELETE /{slug}`: sem `delete_files`, o registro some do Postgres mas a
    pasta continua no disco; com `delete_files=true`, os dois somem — e o
    cache de `local_path` (`register_local_path`) é evictado nos dois casos,
    senão um slug reaproveitado herdaria o `local_path` do projeto apagado
    até o próximo restart (ver ADR 0016)."""
    import os
    import uuid

    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from eltanix.api.deps import require_session
    from eltanix.db.models import ProjectRecord
    from eltanix.db.session import init_engine, session_scope, shutdown_engine
    from eltanix.main import create_app

    init_engine(url)
    try:
        app = create_app()
        app.state.projects_root = tmp_path

        async def _fake_session(request: Request) -> None:
            request.state.is_service = True
            request.state.user_id = None
            request.state.is_admin = False

        app.dependency_overrides[require_session] = _fake_session

        # ── Caso 1: sem delete_files — registro some, pasta fica ───────────
        slug1 = f"del-sem-arquivos-{uuid.uuid4().hex[:8]}"
        pasta1 = tmp_path / slug1
        pasta1.mkdir()
        (pasta1 / "algo.txt").write_text("fica", encoding="utf-8")
        async with session_scope() as session:
            session.add(ProjectRecord(slug=slug1, name="Sem Arquivos", local_path=str(pasta1), default_branch="main"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res1 = await ac.delete(f"/api/projects/{slug1}")
            assert res1.status_code == 200, res1.text
            data1 = res1.json()
            assert data1["files_deleted"] is False
            assert pasta1.is_dir()  # pasta preservada

        async with session_scope() as session:
            rec1 = (await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug1))).scalar_one_or_none()
            assert rec1 is None  # registro removido

        # ── Caso 2: com delete_files=true — registro e pasta somem ─────────
        slug2 = f"del-com-arquivos-{uuid.uuid4().hex[:8]}"
        pasta2 = tmp_path / slug2
        pasta2.mkdir()
        (pasta2 / "algo.txt").write_text("some", encoding="utf-8")
        async with session_scope() as session:
            session.add(ProjectRecord(slug=slug2, name="Com Arquivos", local_path=str(pasta2), default_branch="main"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res2 = await ac.delete(f"/api/projects/{slug2}?delete_files=true")
            assert res2.status_code == 200, res2.text
            data2 = res2.json()
            assert data2["files_deleted"] is True
            assert not pasta2.exists()  # pasta removida de verdade

        async with session_scope() as session:
            rec2 = (await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug2))).scalar_one_or_none()
            assert rec2 is None
    finally:
        await shutdown_engine()


