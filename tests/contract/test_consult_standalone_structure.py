"""批次3独立Consult应用与A2A公开边界门禁。"""

import ast
import hashlib
import inspect
from pathlib import Path

import tomllib

from agent import root_agent
from apps.consult_agent.a2a.card import build_agent_card
from apps.consult_agent.agent import build_consult_agent
from apps.consult_agent.prompts import CONSULT_AGENT_PROMPT
from packages.agent_runtime.model_config import extra_config_for, model_for


REPO_ROOT = Path(__file__).resolve().parents[2]
CONSULT_ROOT = REPO_ROOT / "apps" / "consult_agent"


def _tool_names(agent) -> list[str]:
    return [getattr(tool, "__name__", getattr(tool, "name", "")) for tool in agent.tools]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_consult_builder_has_no_employee_data_dependency_and_only_consult_tools():
    assert set(inspect.signature(build_consult_agent).parameters) == {
        "model_name",
        "model_extra_config",
    }
    consult_agent = build_consult_agent(
        model_name=model_for("consult"),
        model_extra_config=extra_config_for("consult"),
    )
    assert consult_agent.name == "hr_consult_agent"
    assert _tool_names(consult_agent) == ["kb_search", "parse_document"]
    assert all(agent.name != "hr_consult_agent" for agent in root_agent.sub_agents)


def test_consult_prompt_content_remains_frozen():
    assert hashlib.sha256(CONSULT_AGENT_PROMPT.encode()).hexdigest() == (
        "713ad2073084969710e498f4ec4d9df3d75ddca668a3169ceccef8da763084b5"
    )


def test_standalone_consult_does_not_import_forbidden_apps_or_gaia():
    forbidden_prefixes = (
        "agent",
        "apps.orchestrator",
        "apps.employee_data_agent",
        "packages.hr_domain.gaia",
    )
    violations = []
    for path in sorted(CONSULT_ROOT.rglob("*.py")):
        for target in _imports(path):
            if target == "agent" or target.startswith(forbidden_prefixes[1:]):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert not violations, "独立Consult存在禁止依赖：" + ", ".join(violations)


def test_agent_card_uses_frozen_protocol_and_four_skills():
    card = build_agent_card()
    assert card.name == "hr-consult-agent"
    assert card.version == "1.0.0"
    assert card.protocol_version == "0.3.0"
    assert card.preferred_transport == "JSONRPC"
    assert card.url == "http://127.0.0.1:8101/"
    assert card.capabilities.streaming is True
    assert card.default_input_modes == ["text"]
    assert card.default_output_modes == ["text"]
    assert {skill.id for skill in card.skills} == {
        "hr-policy-consultation",
        "hr-benefit-consultation",
        "hr-system-operation-guide",
        "hr-document-question-answering",
    }
    assert all(skill.input_modes == ["text"] for skill in card.skills)
    assert all(skill.output_modes == ["text"] for skill in card.skills)


def test_official_a2a_sdk_is_a_direct_locked_dependency():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "a2a-sdk[http-server]==0.3.7" in project["project"]["dependencies"]
