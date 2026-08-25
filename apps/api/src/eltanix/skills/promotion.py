"""Análise sob demanda de sessões fechadas para sugerir candidatos a skill.

Horizonte 4, item 2 da auditoria arquitetural: o único mecanismo de promoção
que existia (`agent/tools/skills.py::propose_skill`) é manual e de uma única
sessão — o próprio modelo decide, no meio de uma conversa, salvar um padrão
que acabou de usar. Nada olha padrões que se repetem ENTRE sessões diferentes.

Protótipo mínimo, escopo reduzido por decisão do usuário (via AskUserQuestion):
comando sob demanda (não cron), lê sessões já fechadas do Postgres, usa o LLM
pra sugerir candidatos e SÓ sugere — nunca chama `SkillService.propose_and_save`
sozinho. Revisão humana decide o que vira skill de verdade, pelas rotas normais
de `api/routes/skills.py` (`POST /api/skills`).

Fonte de dados: `AgentSessionRecord.task` (o pedido em texto livre que criou a
sessão), não `.summary` — este último é só um status de UI curto ("Executando",
"Sessão encerrada em <branch>", ver `agent/runner.py::_session_summary`/
`close_session`), sem conteúdo suficiente pra detectar padrão nenhum.
"sucesso" aqui é uma heurística barata (sem reconstruir o checkpointer do
LangGraph, fora do escopo do protótipo): `status == "closed"` (encerrada
explicitamente, não abandonada) e `last_failed_call_count == 0` (sem falha
repetida de ferramenta registrada).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.agent import session_store
from eltanix.logging_setup import get_logger
from eltanix.router.engine import RouterEngine
from eltanix.skills.service import SkillService

log = get_logger(__name__)

_VALID_CATEGORIES = {"automation", "analysis", "code", "web", "database"}

# Sessões demais no prompt custam tokens à toa sem ajudar o LLM a achar padrão
# — 20 tasks recentes já é amostra suficiente para um protótipo sob demanda.
_MAX_SESSIONS_DEFAULT = 20
# Um padrão "repetido" pressupõe pelo menos duas sessões pra comparar.
_MIN_SESSIONS_FOR_ANALYSIS = 2

SKILL_ANALYSIS_SYSTEM_PROMPT = """Você analisa pedidos (tasks) de sessões recentes e \
bem-sucedidas de um agente de codificação, procurando PADRÕES REPETIDOS que valeriam \
virar uma skill reutilizável — um preset de prompt de sistema que o agente carrega em \
sessões futuras para não reconstruir o mesmo raciocínio do zero toda vez.

Receberá a lista de tasks (uma por sessão) e os nomes das skills que já existem — não \
sugira nada equivalente ao que já existe.

Só sugira um candidato quando o MESMO tipo de tarefa aparecer em pelo menos DUAS sessões \
diferentes — uma tarefa que ocorreu uma única vez não é "repetida". Se nada se repete, \
responda com uma lista vazia.

Responda em JSON, e SÓ o JSON (sem texto antes ou depois, sem bloco de código), neste \
formato exato:
{"candidates": [{"name": "...", "description": "...", \
"category": "automation|analysis|code|web|database", "rationale": "...", \
"system_prompt_suggestion": "..."}]}

- "name": curto, kebab-case, descreve a tarefa (não o produto).
- "rationale": cite, em poucas palavras, quais tasks (pelo texto) sustentam esse padrão.
- "system_prompt_suggestion": um rascunho de prompt de sistema para a skill — é só um \
ponto de partida, um humano vai revisar e ajustar antes de salvar."""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _strip_fence(texto: str) -> str:
    """Modelos às vezes envolvem o JSON em ```json ... ``` mesmo quando instruídos
    a não fazer isso — melhor tolerar do que falhar o parse por causa disso."""
    return _FENCE_RE.sub("", texto.strip()).strip()


@dataclass(slots=True)
class SkillCandidate:
    name: str
    description: str
    category: str
    rationale: str
    system_prompt_suggestion: str


@dataclass(slots=True)
class SkillPromotionAnalysis:
    candidates: list[SkillCandidate] = field(default_factory=list)
    sessions_analyzed: int = 0
    raw_text: str = ""
    # True quando a resposta do LLM não veio em JSON válido — `candidates` vem
    # vazio nesse caso (mesmo espírito de `review_common.py`: falhar fechado em
    # vez de tentar adivinhar), mas `raw_text` preserva o que o modelo disse
    # para quem for depurar.
    unparseable: bool = False


async def analyze_recent_sessions(
    db: AsyncSession,
    engine: RouterEngine,
    skills: SkillService,
    *,
    project: str | None = None,
    limit: int = _MAX_SESSIONS_DEFAULT,
    source: str = "skills.promotion",
) -> SkillPromotionAnalysis:
    """Uma chamada isolada ao router (mesmo padrão de `agent/review_common.py`)
    — não participa do histórico de nenhuma sessão de agente."""
    registros = await session_store.list_sessions(db, project=project, status="closed", limit=limit)
    tasks = [
        (r.session_id, r.task.strip())
        for r in registros
        if r.task and r.task.strip() and r.last_failed_call_count == 0
    ]
    if len(tasks) < _MIN_SESSIONS_FOR_ANALYSIS:
        return SkillPromotionAnalysis(sessions_analyzed=len(tasks))

    existentes = await skills.list_all()
    nomes_existentes = ", ".join(s.name for s in existentes) or "(nenhuma)"
    corpo = "\n".join(f"- ({sid}) {task}" for sid, task in tasks)

    resultado = await engine.complete(
        requested_model="coding",
        params={
            "messages": [
                {"role": "system", "content": SKILL_ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Skills que já existem (não repetir): {nomes_existentes}\n\n"
                        f"Tasks das sessões recentes:\n{corpo}"
                    ),
                },
            ],
            "temperature": 0,
        },
        source=source,
    )
    escolha = (resultado.payload.get("choices") or [{}])[0]
    texto = (escolha.get("message") or {}).get("content") or ""

    try:
        dados = json.loads(_strip_fence(texto))
        candidatos = [
            SkillCandidate(
                name=str(c["name"]).strip(),
                description=str(c.get("description", "")).strip(),
                category=(
                    c.get("category") if c.get("category") in _VALID_CATEGORIES else "automation"
                ),
                rationale=str(c.get("rationale", "")).strip(),
                system_prompt_suggestion=str(c.get("system_prompt_suggestion", "")).strip(),
            )
            for c in dados.get("candidates", [])
            if c.get("name")
        ]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        log.warning("skills.promotion.unparseable", error=str(exc)[:200], preview=texto[:200])
        return SkillPromotionAnalysis(
            sessions_analyzed=len(tasks), raw_text=texto, unparseable=True
        )

    return SkillPromotionAnalysis(
        candidates=candidatos, sessions_analyzed=len(tasks), raw_text=texto
    )
