"""Rota das regras de contexto por glob (`.novaai_studio/context_rules.yaml`) —
Fase 4 do upgrade do agente, estilo `.cursor/rules`.

Mesmo desenho de `api/routes/approval_policy.py`: o PUT substitui a lista de
regras inteira em vez de expor add/remove por índice — a UI edita a lista em
estado local e salva de uma vez.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field
from ruamel.yaml.comments import CommentedSeq

from novaai_studio.agent import context_rules_editor as editor
from novaai_studio.agent.context_rules import ContextRule, ContextRulesConfig
from novaai_studio.agent.context_rules_config import load_context_rules
from novaai_studio.api.deps import AuthDep, SettingsDep
from novaai_studio.api.routes.workspace import project_fs

router = APIRouter(prefix="/api/agent/context-rules", tags=["agent"], dependencies=[AuthDep])


class ContextRulesUpdateRequest(BaseModel):
    project: str = Field(min_length=1)
    rules: list[ContextRule] = Field(default_factory=list)


@router.get("")
async def get_rules(settings: SettingsDep, project: str) -> ContextRulesConfig:
    root = project_fs(settings, project).root
    return await asyncio.to_thread(load_context_rules, root)


@router.put("")
async def update_rules(
    payload: ContextRulesUpdateRequest, settings: SettingsDep
) -> ContextRulesConfig:
    root = project_fs(settings, payload.project).root

    def _write() -> None:
        data = editor.load(root)
        data["rules"] = CommentedSeq()
        for rule in payload.rules:
            editor.add_rule(data, rule.model_dump(mode="json", exclude_none=True))
        editor.dump(root, data)

    await asyncio.to_thread(_write)
    return await asyncio.to_thread(load_context_rules, root)
