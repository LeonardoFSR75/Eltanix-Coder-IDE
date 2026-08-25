"""Testes de `agent/slash_commands.py::resolve_slash_command` (Fase 2 do upgrade do agente)."""

from __future__ import annotations

import pytest

from novaai_studio.agent.slash_commands import SLASH_COMMANDS, resolve_slash_command


@pytest.mark.parametrize("comando", sorted(SLASH_COMMANDS))
def test_resolve_slash_command_recognizes_every_registered_command(comando: str):
    texto, resolvido = resolve_slash_command(f"{comando} faça a coisa")
    assert resolvido is not None
    assert resolvido.command == comando
    assert texto == "faça a coisa"


def test_resolve_slash_command_plain_text_has_no_command():
    texto, resolvido = resolve_slash_command("implemente uma função de login")
    assert resolvido is None
    assert texto == "implemente uma função de login"


def test_resolve_slash_command_unregistered_slash_is_ignored():
    texto, resolvido = resolve_slash_command("/naoexiste faça algo")
    assert resolvido is None
    assert texto == "/naoexiste faça algo"


def test_resolve_slash_command_without_trailing_text():
    texto, resolvido = resolve_slash_command("/spec")
    assert resolvido is not None
    assert resolvido.command == "/spec"
    assert texto == ""


def test_resolve_slash_command_case_insensitive():
    texto, resolvido = resolve_slash_command("/SPEC crie a especificação")
    assert resolvido is not None
    assert resolvido.command == "/spec"
    assert texto == "crie a especificação"


def test_resolve_slash_command_leading_whitespace():
    texto, resolvido = resolve_slash_command("   /fix corrige o bug")
    assert resolvido is not None
    assert resolvido.command == "/fix"
    assert texto == "corrige o bug"


def test_explain_has_no_forced_skill():
    assert SLASH_COMMANDS["/explain"].skill_name is None


@pytest.mark.parametrize("comando", [c for c in SLASH_COMMANDS.values() if c.command != "/explain"])
def test_every_command_except_explain_has_a_skill_and_mode(comando):
    assert comando.skill_name
    assert comando.suggested_mode


@pytest.mark.asyncio
async def test_list_slash_commands_endpoint_exposes_the_full_catalog():
    from novaai_studio.api.routes.agent import list_slash_commands

    payload = await list_slash_commands()
    comandos = {c["command"]: c for c in payload["commands"]}

    assert set(comandos) == set(SLASH_COMMANDS)
    assert comandos["/spec"]["skill_name"] == "spec-driven-development"
    assert comandos["/spec"]["suggested_mode"] == "plan"
    assert comandos["/explain"]["skill_name"] is None
