"""Operações Git do agente.

A peça central aqui é o **worktree por sessão**. Sem ele, o agente trabalharia
na mesma árvore em que você está editando: um `git checkout -b` do agente
trocaria o branch debaixo do seu editor, e um arquivo escrito por ele
apareceria misturado às suas mudanças não commitadas. Com worktree, a sessão do
agente tem um diretório e um branch próprios, e o seu permanece intocado.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from git import GitCommandError, Repo

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Worktrees do agente vivem aqui, fora da árvore de trabalho e ignorados.
WORKTREE_DIR = ".sicoobito/worktrees"


class GitError(RuntimeError):
    pass


@dataclass(slots=True)
class FileStatus:
    path: str
    status: str  # added | modified | deleted | renamed | untracked


@dataclass(slots=True)
class RepoStatus:
    branch: str
    head: str
    dirty: bool
    files: list[FileStatus]
    ahead: int = 0
    behind: int = 0


@dataclass(slots=True)
class AgentWorktree:
    path: Path
    branch: str
    base_branch: str


def open_repo(root: Path) -> Repo:
    try:
        return Repo(root, search_parent_directories=False)
    except Exception as exc:
        raise GitError(f"{root} não é um repositório Git: {exc}") from exc


def status(root: Path) -> RepoStatus:
    repo = open_repo(root)

    files: list[FileStatus] = []
    for item in repo.index.diff(None):  # working tree vs index
        files.append(FileStatus(path=item.a_path, status=_change_label(item.change_type)))
    try:
        for item in repo.index.diff("HEAD"):  # index vs HEAD
            files.append(FileStatus(path=item.a_path, status="staged"))
    except GitCommandError:
        # Repositório sem commit ainda: não há HEAD para comparar.
        pass
    files.extend(FileStatus(path=p, status="untracked") for p in repo.untracked_files)

    try:
        branch = repo.active_branch.name
    except TypeError:  # HEAD destacado
        branch = f"(detached {repo.head.commit.hexsha[:8]})"

    head = repo.head.commit.hexsha if repo.head.is_valid() else ""
    return RepoStatus(
        branch=branch,
        head=head,
        dirty=repo.is_dirty(untracked_files=True),
        files=files,
    )


def _change_label(change_type: str | None) -> str:
    return {
        "A": "added",
        "D": "deleted",
        "M": "modified",
        "R": "renamed",
        "T": "typechange",
    }.get(change_type or "M", "modified")


def diff(root: Path, *, staged: bool = False, path: str | None = None) -> str:
    repo = open_repo(root)
    args = ["--no-color", "--unified=3"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    try:
        return repo.git.diff(*args)
    except GitCommandError as exc:
        raise GitError(f"git diff falhou: {exc}") from exc


def _ensure_excluded(repo: Repo) -> None:
    """Garante que os worktrees do agente não sujem o `git status` do usuário.

    Vai em `.git/info/exclude`, não no `.gitignore`: o `.gitignore` é versionado
    e pertence ao projeto, então escrever nele criaria uma mudança que o usuário
    não pediu e teria de commitar. O `info/exclude` é local ao clone e existe
    exatamente para isto.
    """
    exclude = Path(repo.git_dir) / "info" / "exclude"
    entrada = "/.sicoobito/"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        atual = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if entrada in atual.splitlines():
            return
        prefixo = "" if not atual or atual.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefixo}# worktrees de sessão do SicoobitoCode\n{entrada}\n")
        log.debug("git.exclude.added", path=str(exclude))
    except OSError as exc:
        # Não é fatal: o pior caso é o worktree aparecer como untracked.
        log.warning("git.exclude.failed", error=str(exc))


def create_worktree(
    root: Path, session_id: str, *, base_branch: str | None = None
) -> AgentWorktree:
    """Cria um worktree e um branch dedicados a uma sessão do agente."""
    repo = open_repo(root)
    _ensure_excluded(repo)

    if not repo.head.is_valid():
        raise GitError(
            "O repositório não tem nenhum commit ainda. Faça o commit inicial "
            "antes de rodar o agente."
        )

    try:
        base = base_branch or repo.active_branch.name
    except TypeError:
        base = repo.head.commit.hexsha

    branch = f"sicoobito/{session_id}"
    target = (root / WORKTREE_DIR / session_id).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        # Sessão retomada: reaproveita o worktree existente em vez de falhar.
        log.info("git.worktree.reused", path=str(target), branch=branch)
        return AgentWorktree(path=target, branch=branch, base_branch=base)

    try:
        # `--` barra qualquer um dos dois argumentos posicionais de ser lido
        # como flag — mesma defesa já aplicada aos outros `repo.git.*` deste
        # arquivo. Não é explorável hoje (branch é sempre `sicoobito/<uuid>` e
        # base nunca vem de fora), mas não custa manter a mesma disciplina.
        repo.git.worktree("add", "-b", branch, "--", str(target), base)
    except GitCommandError as exc:
        raise GitError(f"não foi possível criar o worktree: {exc}") from exc

    log.info("git.worktree.created", path=str(target), branch=branch, base=base)
    return AgentWorktree(path=target, branch=branch, base_branch=base)


def remove_worktree(root: Path, session_id: str, *, delete_branch: bool = False) -> None:
    repo = open_repo(root)
    target = (root / WORKTREE_DIR / session_id).resolve()

    try:
        repo.git.worktree("remove", "--force", str(target))
    except GitCommandError as exc:
        log.warning("git.worktree.remove_failed", path=str(target), error=str(exc))
        # `worktree remove` falha se o diretório já sumiu; limpamos o registro
        # e o resíduo em disco para não deixar worktree fantasma.
        try:
            repo.git.worktree("prune")
        except GitCommandError:
            pass
        shutil.rmtree(target, ignore_errors=True)

    if delete_branch:
        try:
            repo.git.branch("-D", f"sicoobito/{session_id}")
        except GitCommandError as exc:
            log.warning("git.branch.delete_failed", session=session_id, error=str(exc))


def commit(
    root: Path, message: str, *, paths: list[str] | None = None, author_name: str | None = None
) -> str:
    """Commita e devolve o SHA. `paths` vazio significa tudo que mudou."""
    repo = open_repo(root)

    if paths:
        repo.index.add(paths)
    else:
        repo.git.add("-A")

    if not repo.is_dirty(index=True, working_tree=False, untracked_files=True):
        raise GitError("Nada para commitar.")

    # Marca a autoria: numa revisão futura importa saber o que veio do agente.
    author = author_name or "SicoobitoCode Agent"
    with repo.config_writer() as config:
        config.set_value("user", "name", repo.config_reader().get_value("user", "name", author))

    committed = repo.index.commit(message)
    log.info("git.commit", sha=committed.hexsha[:8], message=message.splitlines()[0][:80])
    return committed.hexsha


def push(root: Path, branch: str, *, remote: str = "origin", set_upstream: bool = True) -> None:
    repo = open_repo(root)
    if remote not in {r.name for r in repo.remotes}:
        raise GitError(f"Remote '{remote}' não existe neste repositório.")
    try:
        args = ["-u", remote, branch] if set_upstream else [remote, branch]
        repo.git.push(*args)
    except GitCommandError as exc:
        raise GitError(f"git push falhou: {exc}") from exc
    log.info("git.push", branch=branch, remote=remote)


def log_recent(root: Path, limit: int = 20) -> list[dict[str, str]]:
    repo = open_repo(root)
    if not repo.head.is_valid():
        return []
    return [
        {
            "sha": c.hexsha[:8],
            "author": str(c.author),
            "date": datetime.fromtimestamp(c.committed_date, tz=UTC).isoformat(),
            "message": c.message.splitlines()[0] if c.message else "",
        }
        for c in repo.iter_commits(max_count=limit)
    ]


def remote_url(root: Path, remote: str = "origin") -> str | None:
    repo = open_repo(root)
    for candidate in repo.remotes:
        if candidate.name == remote:
            return next(iter(candidate.urls), None)
    return None
