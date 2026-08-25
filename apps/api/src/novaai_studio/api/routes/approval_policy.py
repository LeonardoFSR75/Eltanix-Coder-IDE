"""Rota da política de auto-aprovação (`.novaai_studio/approval_policy.yaml`).

`agent/approval_policy_editor.py` já tinha as funções de round-trip
(`load`/`dump`/`add_rule`/`remove_rule`/`set_second_opinion`) prontas desde
que a política nasceu, com a nota explícita de que faltava só uma tela — esta
rota é essa ligação. O PUT substitui a lista de regras inteira em vez de
expor add/remove por índice: a UI edita a lista em estado local e salva de
uma vez, mesmo padrão já usado pelas Instruções no `CustomizationsPopover`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field
from ruamel.yaml.comments import CommentedSeq

from novaai_studio.agent import approval_policy_editor as editor
from novaai_studio.agent.approval_policy import ApprovalPolicy, EditPathRule, ExecCommandRule
from novaai_studio.agent.approval_policy_config import load_approval_policy
from novaai_studio.api.deps import AuthDep, SettingsDep
from novaai_studio.api.routes.workspace import project_fs

router = APIRouter(prefix="/api/agent/approval-policy", tags=["agent"], dependencies=[AuthDep])


class ApprovalPolicyUpdateRequest(BaseModel):
    project: str = Field(min_length=1)
    second_opinion: bool = False
    rules: list[EditPathRule | ExecCommandRule] = Field(default_factory=list)


@router.get("")
async def get_policy(settings: SettingsDep, project: str) -> ApprovalPolicy:
    root = project_fs(settings, project).root
    return await asyncio.to_thread(load_approval_policy, root)


@router.put("")
async def update_policy(
    payload: ApprovalPolicyUpdateRequest, settings: SettingsDep
) -> ApprovalPolicy:
    root = project_fs(settings, payload.project).root

    def _write() -> None:
        data = editor.load(root)
        editor.set_second_opinion(data, payload.second_opinion)
        data["rules"] = CommentedSeq()
        for rule in payload.rules:
            editor.add_rule(data, rule.model_dump(mode="json", exclude_none=True))
        editor.dump(root, data)

    await asyncio.to_thread(_write)
    return await asyncio.to_thread(load_approval_policy, root)
