"""Rotas para gestão do Quadro Trello/Kanban do projeto com persistência em
.sicoobito/kanban.json."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.config import get_settings
from sicoobito.logging_setup import get_logger
from sicoobito.workspace.projects import resolve

log = get_logger(__name__)

router = APIRouter(prefix="/api/projects/{slug}/trello", tags=["trello"], dependencies=[AuthDep])

CardStatus = Literal["todo", "in_progress", "review", "done"]
CardPriority = Literal["high", "medium", "low"]


class TrelloCardCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255, description="Título da tarefa/cartão")
    description: str = Field(default="", description="Descrição detalhada")
    status: CardStatus = Field(default="todo")
    priority: CardPriority = Field(default="medium")
    created_by_agent: bool = Field(default=False)


class TrelloCardUpdateIn(BaseModel):
    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    status: CardStatus | None = Field(default=None)
    priority: CardPriority | None = Field(default=None)


def _projects_root(request: Request) -> Path:
    raiz = getattr(request.app.state, "projects_root", None) or get_settings().projects_root
    if isinstance(raiz, Path):
        return raiz
    if raiz:
        return Path(str(raiz))
    return Path(".")


def get_kanban_file(project_path: Path) -> Path:
    sicoobito_dir = project_path / ".sicoobito"
    sicoobito_dir.mkdir(parents=True, exist_ok=True)
    return sicoobito_dir / "kanban.json"


def load_kanban_cards(project_path: Path) -> list[dict[str, Any]]:
    kanban_file = get_kanban_file(project_path)
    if not kanban_file.exists():
        samples: list[dict[str, Any]] = [
            {
                "id": "card-1",
                "title": "Configurar ambiente do projeto",
                "description": "Verificar dependências, Docker Compose e banco de dados local.",
                "status": "done",
                "priority": "high",
                "created_at": time.strftime("%Y-%m-%d %H:%M"),
                "updated_at": time.strftime("%Y-%m-%d %H:%M"),
                "created_by_agent": False,
            },
            {
                "id": "card-2",
                "title": "Mapear AST & símbolos do projeto",
                "description": "Indexar módulos e analisar relacionamentos de código.",
                "status": "in_progress",
                "priority": "high",
                "created_at": time.strftime("%Y-%m-%d %H:%M"),
                "updated_at": time.strftime("%Y-%m-%d %H:%M"),
                "created_by_agent": True,
            },
            {
                "id": "card-3",
                "title": "Revisar cobertura de testes",
                "description": "Garantir execução limpa dos testes automatizados.",
                "status": "todo",
                "priority": "medium",
                "created_at": time.strftime("%Y-%m-%d %H:%M"),
                "updated_at": time.strftime("%Y-%m-%d %H:%M"),
                "created_by_agent": False,
            },
        ]
        save_kanban_cards(project_path, samples)
        return samples

    try:
        data = json.loads(kanban_file.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, list):
            return data
    except Exception as exc:
        log.warning("trello.load_failed", project=project_path.name, error=str(exc))
    return []


def save_kanban_cards(project_path: Path, cards: list[dict[str, Any]]) -> None:
    kanban_file = get_kanban_file(project_path)
    try:
        kanban_file.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.error("trello.save_failed", project=project_path.name, error=str(exc))


@router.get("")
async def list_project_trello_cards(slug: str, request: Request) -> dict[str, Any]:
    """Lista todos os cartões do Quadro Trello/Kanban do projeto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    cards = load_kanban_cards(project_path)
    return {
        "project": slug,
        "count": len(cards),
        "cards": cards,
    }


@router.post("")
async def create_project_trello_card(
    slug: str, payload: TrelloCardCreateIn, request: Request
) -> dict[str, Any]:
    """Cria um novo cartão no Quadro Trello do projeto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    cards = load_kanban_cards(project_path)
    card_id = f"card-{int(time.time() * 1000)}"
    now = time.strftime("%Y-%m-%d %H:%M")

    new_card: dict[str, Any] = {
        "id": card_id,
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "status": payload.status,
        "priority": payload.priority,
        "created_at": now,
        "updated_at": now,
        "created_by_agent": payload.created_by_agent,
    }

    cards.append(new_card)
    save_kanban_cards(project_path, cards)
    log.info("trello.card_created", slug=slug, card_id=card_id, title=payload.title)

    return {
        "ok": True,
        "card": new_card,
    }


@router.put("/{card_id}")
async def update_project_trello_card(
    slug: str, card_id: str, payload: TrelloCardUpdateIn, request: Request
) -> dict[str, Any]:
    """Atualiza o título, descrição, status ou prioridade de um cartão."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    cards = load_kanban_cards(project_path)
    target_card = None

    for c in cards:
        if c.get("id") == card_id:
            target_card = c
            break

    if not target_card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Cartão '{card_id}' não encontrado."
        )

    if payload.title is not None:
        target_card["title"] = payload.title.strip()
    if payload.description is not None:
        target_card["description"] = payload.description.strip()
    if payload.status is not None:
        target_card["status"] = payload.status
    if payload.priority is not None:
        target_card["priority"] = payload.priority

    target_card["updated_at"] = time.strftime("%Y-%m-%d %H:%M")

    save_kanban_cards(project_path, cards)
    log.info("trello.card_updated", slug=slug, card_id=card_id)

    return {
        "ok": True,
        "card": target_card,
    }


@router.delete("/{card_id}")
async def delete_project_trello_card(slug: str, card_id: str, request: Request) -> dict[str, Any]:
    """Remove um cartão do Quadro Trello do projeto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    cards = load_kanban_cards(project_path)
    new_cards = [c for c in cards if c.get("id") != card_id]

    if len(new_cards) == len(cards):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Cartão '{card_id}' não encontrado."
        )

    save_kanban_cards(project_path, new_cards)
    log.info("trello.card_deleted", slug=slug, card_id=card_id)

    return {
        "ok": True,
        "id": card_id,
    }
