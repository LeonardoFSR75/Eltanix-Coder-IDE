"""Operações Git do agente.

A peça central aqui é o **worktree por sessão**. Sem ele, o agente trabalharia
na mesma árvore em que você está editando: um `git checkout -b` do agente
trocaria o branch debaixo do seu editor, e um arquivo escrito por ele
apareceria misturado às suas mudanças não commitadas. Com worktree, a sessão do
agente tem um diretório e um branch próprios, e o seu permanece intocado.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from git import GitCommandError, Repo

from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

# Worktrees do agente vivem aqui, fora da árvore de trabalho e ignorados.
WORKTREE_DIR = ".novaai_studio/worktrees"

# `repo.git.push(...)` (rede/SSH) roda sem timeout algum por padrão — uma
# passphrase SSH pedida interativamente ou um host inalcançável trava o
# processo (e, se chamado via `asyncio.to_thread`, o worker do pool) para
# sempre. GitPython não suporta `kill_after_timeout` no Windows (levanta
# GitCommandError), então só aplicamos onde o runtime de produção (containers
# Linux, ver docker-compose.yml) de fato suporta.
_PUSH_TIMEOUT_KWARGS: dict[str, float] = (
    {} if sys.platform == "win32" else {"kill_after_timeout": 30.0}
)


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


@dataclass(slots=True)
class BlameHunk:
    start_line: int
    end_line: int
    sha: str
    author: str
    date: str
    message: str


@dataclass(slots=True)
class CoChangeEntry:
    path: str
    count: int


def _bootstrap_repo(root: Path, repo: Repo) -> Repo:
    """Inicializa a árvore mínima do repositório para permitir trabalho do agente.

    Quando a pasta do projeto ainda é um diretório comum, o agente precisa
    criar um repo antes de qualquer worktree ou operação de branch. Sem este
    bootstrap, o runtime falha do lado do Git em vez de solucionar a condição
    de início do projeto.
    """
    try:
        gitignore_path = root / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(
                ".novaai_studio/\nnode_modules/\n__pycache__/\n", encoding="utf-8"
            )
        if repo.head.is_valid():
            return repo
        repo.index.add([str(gitignore_path.relative_to(root))])
        repo.index.commit("Initial commit")
        log.info("git.auto_initial_commit.created", root=str(root))
    except Exception as exc:
        log.warning("git.auto_initial_commit.failed", root=str(root), error=str(exc)[:200])
    return repo


def ensure_repo(root: Path) -> Repo:
    """Garante que um diretório do projeto tenha uma estrutura Git válida."""
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise GitError(f"{root} não existe ou não é um diretório válido.")

    git_dir = root / ".git"
    if not git_dir.exists():
        try:
            repo = Repo.init(root, initial_branch="main")
            return _bootstrap_repo(root, repo)
        except Exception as exc:
            msg = f"não foi possível inicializar o repositório Git em {root}: {exc}"
            raise GitError(msg) from exc

    try:
        return Repo(root, search_parent_directories=False)
    except Exception as exc:
        raise GitError(f"{root} não é um repositório Git válido: {exc}") from exc


def open_repo(root: Path) -> Repo:
    try:
        return Repo(root, search_parent_directories=False)
    except Exception as exc:
        raise GitError(f"{root} não é um repositório Git: {exc}") from exc


def status(root: Path) -> RepoStatus:
    repo = open_repo(root)

    files: list[FileStatus] = []
    try:
        for item in repo.index.diff(None):  # working tree vs index
            files.append(FileStatus(path=item.a_path, status=_change_label(item.change_type)))
    except Exception:
        pass

    try:
        for item in repo.index.diff("HEAD"):  # index vs HEAD
            files.append(FileStatus(path=item.a_path, status="staged"))
    except Exception:
        # Repositório sem commit ainda: não há HEAD para comparar.
        pass

    try:
        files.extend(FileStatus(path=p, status="untracked") for p in repo.untracked_files)
    except Exception:
        pass

    branch = "main"
    try:
        branch = repo.active_branch.name
    except Exception:
        try:
            head_sha = repo.head.commit.hexsha[:8]
            branch = f"(detached {head_sha})"
        except Exception:
            branch = "main"

    head = ""
    try:
        if repo.head.is_valid():
            head = repo.head.commit.hexsha
    except Exception:
        head = ""

    dirty = False
    try:
        dirty = repo.is_dirty(untracked_files=True)
    except Exception:
        dirty = len(files) > 0

    return RepoStatus(
        branch=branch,
        head=head,
        dirty=dirty,
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
    entrada = "/.novaai_studio/"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        atual = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if entrada in atual.splitlines():
            return
        prefixo = "" if not atual or atual.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefixo}# worktrees de sessão do NovaAI Studio\n{entrada}\n")
        log.debug("git.exclude.added", path=str(exclude))
    except OSError as exc:
        # Não é fatal: o pior caso é o worktree aparecer como untracked.
        log.warning("git.exclude.failed", error=str(exc))


def _link_or_share_env(root: Path, target: Path) -> None:
    """Compartilha os ambientes (.venv, node_modules, vendor, .env) do projeto raiz com o
    worktree."""
    import os

    env_dirs = [".venv", "node_modules", "vendor"]
    for dir_name in env_dirs:
        src = root / dir_name
        dst = target / dir_name
        if src.exists() and not dst.exists():
            try:
                if sys.platform == "win32":
                    import _winapi

                    _winapi.CreateJunction(str(src), str(dst))
                else:
                    os.symlink(src, dst, target_is_directory=True)
                log.info("git.worktree.env_linked", dir=dir_name, target=str(target))
            except Exception as exc:
                log.warning("git.worktree.env_link_failed", dir=dir_name, error=str(exc))

    env_file_src = root / ".env"
    env_file_dst = target / ".env"
    if env_file_src.exists() and not env_file_dst.exists():
        try:
            shutil.copy2(env_file_src, env_file_dst)
        except Exception:
            pass


def _sync_uncommitted_state(root: Path, target: Path) -> None:
    """Copia alterações não commitadas e arquivos untracked do projeto raiz para o worktree."""
    ignored = {".git", ".novaai_studio", ".venv", "node_modules", "vendor", "__pycache__"}
    try:
        repo_status = status(root)
        for f in repo_status.files:
            rel_p = Path(f.path)
            if any(part in ignored for part in rel_p.parts):
                continue
            src_file = root / rel_p
            dst_file = target / rel_p
            if src_file.is_file():
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
        log.info(
            "git.worktree.uncommitted_synced", target=str(target), count=len(repo_status.files)
        )
    except Exception as exc:
        log.warning("git.worktree.sync_uncommitted_failed", error=str(exc))


def create_worktree(
    root: Path, session_id: str, *, base_branch: str | None = None
) -> AgentWorktree:
    """Cria um worktree e um branch dedicados a uma sessão do agente."""
    repo = ensure_repo(root)
    _ensure_excluded(repo)

    if not repo.head.is_valid():
        try:
            gitignore_path = root / ".gitignore"
            if not gitignore_path.exists():
                gitignore_path.write_text(
                    ".novaai_studio/\nnode_modules/\n__pycache__/\n", encoding="utf-8"
                )
            repo.index.add([str(gitignore_path.relative_to(root))])
            repo.index.commit("Initial commit")
            log.info("git.auto_initial_commit.created", root=str(root))
        except Exception as exc:
            log.warning("git.auto_initial_commit.failed", root=str(root), error=str(exc))
            raise GitError(
                "O repositório não tem nenhum commit ainda. Faça o commit inicial "
                "antes de rodar o agente."
            ) from exc

    try:
        base = base_branch or repo.active_branch.name
    except TypeError:
        base = repo.head.commit.hexsha

    branch = f"novaai_studio/{session_id}"
    target = (root / WORKTREE_DIR / session_id).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        # Sessão retomada: reaproveita o worktree existente em vez de falhar.
        _link_or_share_env(root, target)
        log.info("git.worktree.reused", path=str(target), branch=branch)
        return AgentWorktree(path=target, branch=branch, base_branch=base)

    try:
        # `--` barra qualquer um dos dois argumentos posicionais de ser lido
        # como flag — mesma defesa já aplicada aos outros `repo.git.*` deste
        # arquivo. Não é explorável hoje (branch é sempre `novaai_studio/<uuid>` e
        # base nunca vem de fora), mas não custa manter a mesma disciplina.
        repo.git.worktree("add", "-b", branch, "--", str(target), base)
    except GitCommandError as exc:
        raise GitError(f"não foi possível criar o worktree: {exc}") from exc

    _link_or_share_env(root, target)
    _sync_uncommitted_state(root, target)
    log.info("git.worktree.created", path=str(target), branch=branch, base=base)
    return AgentWorktree(path=target, branch=branch, base_branch=base)


def remove_worktree(root: Path, session_id: str, *, delete_branch: bool = False) -> None:
    repo = open_repo(root)
    target = (root / WORKTREE_DIR / session_id).resolve()

    if target.exists():
        import os

        for dir_name in [".venv", "node_modules", "vendor"]:
            junc = target / dir_name
            if junc.exists():
                try:
                    if sys.platform == "win32":
                        os.rmdir(junc)
                    else:
                        os.unlink(junc)
                except Exception:
                    pass

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
            repo.git.branch("-D", f"novaai_studio/{session_id}")
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
    author = author_name or "NovaAI Studio Agent"
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
        repo.git.push(*args, **_PUSH_TIMEOUT_KWARGS)
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


def blame(root: Path, path: str, rev: str = "HEAD") -> list[BlameHunk]:
    """Linha a linha: quem tocou por último em cada trecho do arquivo.

    `Repo.blame` devolve os hunks já em ordem de arquivo — um `(commit, linhas)`
    por trecho contíguo de mesma autoria. Só precisamos acumular o número da
    linha conforme avançamos, sem reprocessar nada.
    """
    repo = open_repo(root)
    try:
        entradas = repo.blame(rev, path)
    except GitCommandError as exc:
        raise GitError(f"git blame falhou: {exc}") from exc

    hunks: list[BlameHunk] = []
    linha = 1
    for item in entradas or []:
        commit, linhas = item
        quantidade = len(linhas) if hasattr(linhas, "__len__") else 1
        commit_msg = str(getattr(commit, "message", "") or "").splitlines()
        first_line = commit_msg[0] if commit_msg else ""
        hunks.append(
            BlameHunk(
                start_line=linha,
                end_line=linha + quantidade - 1,
                sha=str(getattr(commit, "hexsha", ""))[:8],
                author=str(getattr(commit, "author", "")),
                date=datetime.fromtimestamp(
                    int(getattr(commit, "committed_date", 0)), tz=UTC
                ).isoformat(),
                message=first_line,
            )
        )
        linha += quantidade
    return hunks


def co_change(root: Path, path: str, limit: int = 50) -> list[CoChangeEntry]:
    """Quais outros arquivos aparecem nos mesmos commits que `path`.

    Sem grafo persistido: percorre os últimos `limit` commits que tocaram o
    arquivo e conta com que frequência cada outro arquivo aparece junto. Custo
    proporcional a `limit`, não ao tamanho do repositório.
    """
    repo = open_repo(root)
    if not repo.head.is_valid():
        return []

    contagem: dict[str, int] = {}
    for commit in repo.iter_commits(paths=path, max_count=limit):
        try:
            tocados = commit.stats.files.keys()
        except GitCommandError:
            continue
        for outro in tocados:
            outro_str = str(outro)
            if outro_str == path:
                continue
            contagem[outro_str] = contagem.get(outro_str, 0) + 1

    ordenado = sorted(contagem.items(), key=lambda par: par[1], reverse=True)
    return [CoChangeEntry(path=p, count=c) for p, c in ordenado[:20]]


def remote_url(root: Path, remote: str = "origin") -> str | None:
    repo = open_repo(root)
    for candidate in repo.remotes:
        if candidate.name == remote:
            return next(iter(candidate.urls), None)
    return None


def _get_git_config_val(key: str, scope: str = "global", root: Path | None = None) -> str:
    cmd = ["git", "config"]
    if scope == "global":
        cmd.append("--global")
    elif scope == "local" and root:
        cmd.extend(["--file", str(root / ".git" / "config")])
    cmd.extend(["--get", key])

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(root) if root and root.exists() else None,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception as exc:
        log.debug("git.config.get_failed", key=key, error=str(exc))
    return ""


def get_git_user_config(root: Path | None = None) -> dict[str, Any]:
    """Retorna as configurações do Git (user.name, user.email, etc) e chaves SSH."""
    name = _get_git_config_val("user.name", scope="global", root=root)
    email = _get_git_config_val("user.email", scope="global", root=root)
    default_branch = _get_git_config_val("init.defaultBranch", scope="global", root=root) or "main"
    autocrlf = _get_git_config_val("core.autocrlf", scope="global", root=root) or "input"
    gpg_sign = _get_git_config_val("commit.gpgsign", scope="global", root=root) == "true"
    signing_key = _get_git_config_val("user.signingkey", scope="global", root=root)

    local_name = _get_git_config_val("user.name", scope="local", root=root) if root else ""
    local_email = _get_git_config_val("user.email", scope="local", root=root) if root else ""

    # Verifica presença de chaves SSH
    ssh_dir = Path.home() / ".ssh"
    ssh_keys: list[str] = []
    if ssh_dir.exists() and ssh_dir.is_dir():
        for fn in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub", "id_dsa.pub"]:
            if (ssh_dir / fn).exists():
                ssh_keys.append(fn.replace(".pub", ""))

    return {
        "user_name": name,
        "user_email": email,
        "default_branch": default_branch,
        "autocrlf": autocrlf,
        "gpg_sign": gpg_sign,
        "signing_key": signing_key,
        "local_user_name": local_name or None,
        "local_user_email": local_email or None,
        "ssh_keys": ssh_keys,
        "has_ssh": len(ssh_keys) > 0,
    }


def update_git_user_config(
    user_name: str | None = None,
    user_email: str | None = None,
    default_branch: str | None = None,
    autocrlf: str | None = None,
    gpg_sign: bool | None = None,
    signing_key: str | None = None,
    scope: str = "global",
    root: Path | None = None,
) -> dict[str, Any]:
    """Atualiza a configuração do Git (global ou local no repositório)."""
    updates: dict[str, str] = {}
    if user_name is not None:
        updates["user.name"] = user_name.strip()
    if user_email is not None:
        updates["user.email"] = user_email.strip()
    if default_branch is not None:
        updates["init.defaultBranch"] = default_branch.strip()
    if autocrlf is not None:
        updates["core.autocrlf"] = autocrlf.strip()
    if gpg_sign is not None:
        updates["commit.gpgsign"] = "true" if gpg_sign else "false"
    if signing_key is not None:
        updates["user.signingkey"] = signing_key.strip()

    cwd = str(root) if root and root.exists() else None
    if scope == "local" and root and root.exists() and not (root / ".git").exists():
        try:
            from git import Repo

            Repo.init(root)
        except Exception as exc:
            log.warning("git.init.auto_failed", path=str(root), error=str(exc))

    flag = "--global" if scope == "global" else "--local"

    for key, val in updates.items():
        cmd = ["git", "config", flag, key, val]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, cwd=cwd)
            if res.returncode != 0:
                raise GitError(f"Falha ao executar `git config {flag} {key}`: {res.stderr.strip()}")
        except Exception as exc:
            raise GitError(f"Erro ao atualizar git config: {exc}") from exc

    return get_git_user_config(root=root)
