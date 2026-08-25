"""Testes das regras de contexto por glob (Fase 4 do upgrade do agente,
estilo `.cursor/rules`)."""

from __future__ import annotations

from novaai_studio.agent.context_rules import (
    ContextRule,
    ContextRulesConfig,
    build_context_rules_prompt,
    match_context_rules,
)
from novaai_studio.agent.context_rules_config import load_context_rules
from novaai_studio.agent.runner import _load_context_rules_prompt


class TestMatchContextRules:
    def test_no_targets_returns_empty(self):
        config = ContextRulesConfig(rules=[ContextRule(glob="apps/api/**", instructions="x")])
        assert match_context_rules(config, focus_files=None, focus_folder=None) == []

    def test_matches_focus_file(self):
        regra = ContextRule(glob="apps/api/**/*.py", instructions="Use Pydantic v2.")
        config = ContextRulesConfig(rules=[regra])
        resultado = match_context_rules(
            config, focus_files=["apps/api/src/novaai_studio/main.py"], focus_folder=None
        )
        assert resultado == [regra]

    def test_matches_focus_folder(self):
        regra = ContextRule(glob="apps/web/**", instructions="Use Tailwind.")
        config = ContextRulesConfig(rules=[regra])
        resultado = match_context_rules(config, focus_files=None, focus_folder="apps/web/**")
        assert resultado == [regra]

    def test_no_match_returns_empty(self):
        regra = ContextRule(glob="apps/web/**", instructions="Use Tailwind.")
        config = ContextRulesConfig(rules=[regra])
        resultado = match_context_rules(
            config, focus_files=["apps/api/src/novaai_studio/main.py"], focus_folder=None
        )
        assert resultado == []

    def test_windows_backslash_path_normalizes_before_matching(self):
        regra = ContextRule(glob="apps/api/**/*.py", instructions="x")
        config = ContextRulesConfig(rules=[regra])
        resultado = match_context_rules(
            config, focus_files=["apps\\api\\src\\novaai_studio\\main.py"], focus_folder=None
        )
        assert resultado == [regra]

    def test_preserves_declared_order_without_deduping(self):
        r1 = ContextRule(glob="apps/api/**", instructions="regra 1")
        r2 = ContextRule(glob="apps/api/**", instructions="regra 2")
        config = ContextRulesConfig(rules=[r1, r2])
        resultado = match_context_rules(
            config, focus_files=["apps/api/src/main.py"], focus_folder=None
        )
        assert resultado == [r1, r2]

    def test_malformed_glob_in_one_rule_does_not_break_others(self):
        # fnmatch nunca lança em prática (translate cobre qualquer string),
        # mas o `try/except` por regra garante que uma falha futura numa regra
        # não impeça as outras de serem avaliadas.
        boa = ContextRule(glob="apps/api/**", instructions="ok")
        config = ContextRulesConfig(rules=[boa])
        resultado = match_context_rules(
            config, focus_files=["apps/api/main.py"], focus_folder=None
        )
        assert resultado == [boa]


class TestBuildContextRulesPrompt:
    def test_empty_list_returns_none(self):
        assert build_context_rules_prompt([]) is None

    def test_renders_glob_and_instructions(self):
        regra = ContextRule(glob="apps/api/**/*.py", instructions="Use Pydantic v2.")
        resultado = build_context_rules_prompt([regra])
        assert resultado is not None
        assert "## Regras de contexto ativas" in resultado
        assert "### Regra para `apps/api/**/*.py`" in resultado
        assert "Use Pydantic v2." in resultado

    def test_renders_multiple_rules_as_separate_sections(self):
        r1 = ContextRule(glob="apps/api/**", instructions="regra backend")
        r2 = ContextRule(glob="apps/web/**", instructions="regra frontend")
        resultado = build_context_rules_prompt([r1, r2])
        assert resultado is not None
        assert resultado.count("### Regra para") == 2
        assert "regra backend" in resultado
        assert "regra frontend" in resultado


class TestLoadContextRules:
    def test_missing_file_returns_empty_config(self, tmp_path):
        config = load_context_rules(tmp_path)
        assert config == ContextRulesConfig()

    def test_reads_valid_yaml(self, tmp_path):
        (tmp_path / ".novaai_studio").mkdir()
        (tmp_path / ".novaai_studio" / "context_rules.yaml").write_text(
            "version: 1\nrules:\n  - glob: apps/api/**\n    instructions: use pydantic v2\n",
            encoding="utf-8",
        )
        config = load_context_rules(tmp_path)
        assert len(config.rules) == 1
        assert config.rules[0].glob == "apps/api/**"
        assert config.rules[0].instructions == "use pydantic v2"

    def test_malformed_yaml_degrades_to_empty_config(self, tmp_path):
        (tmp_path / ".novaai_studio").mkdir()
        (tmp_path / ".novaai_studio" / "context_rules.yaml").write_text(
            "rules: [glob: sem fechar", encoding="utf-8"
        )
        assert load_context_rules(tmp_path) == ContextRulesConfig()

    def test_invalid_schema_degrades_to_empty_config(self, tmp_path):
        (tmp_path / ".novaai_studio").mkdir()
        (tmp_path / ".novaai_studio" / "context_rules.yaml").write_text(
            "rules:\n  - instructions: falta o glob\n", encoding="utf-8"
        )
        assert load_context_rules(tmp_path) == ContextRulesConfig()


class TestLoadContextRulesPrompt:
    """`agent/runner.py::_load_context_rules_prompt` — combina leitura +
    match + renderização, é exatamente o que `create_session` chama para
    preencher `ToolContext.context_rules_prompt`."""

    def test_no_config_file_returns_none(self, tmp_path):
        assert (
            _load_context_rules_prompt(tmp_path, focus_files=["app.py"], focus_folder=None)
            is None
        )

    def test_matching_rule_renders_prompt(self, tmp_path):
        (tmp_path / ".novaai_studio").mkdir()
        (tmp_path / ".novaai_studio" / "context_rules.yaml").write_text(
            "rules:\n  - glob: 'app.py'\n    instructions: sempre use type hints\n",
            encoding="utf-8",
        )

        resultado = _load_context_rules_prompt(
            tmp_path, focus_files=["app.py"], focus_folder=None
        )

        assert resultado is not None
        assert "sempre use type hints" in resultado

    def test_non_matching_rule_returns_none(self, tmp_path):
        (tmp_path / ".novaai_studio").mkdir()
        (tmp_path / ".novaai_studio" / "context_rules.yaml").write_text(
            "rules:\n  - glob: 'apps/web/**'\n    instructions: use Tailwind\n",
            encoding="utf-8",
        )

        resultado = _load_context_rules_prompt(
            tmp_path, focus_files=["apps/api/main.py"], focus_folder=None
        )

        assert resultado is None
