"""新批次4阶段A：独立Employee Data应用结构门禁。"""

import ast
import inspect
from pathlib import Path

from apps.employee_data_agent.a2a.card import build_agent_card
from apps.employee_data_agent.agent import build_employee_data_agent


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "apps" / "employee_data_agent"
SHARED_A2A_ROOT = REPO_ROOT / "packages" / "agent_runtime" / "a2a"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _tool_names(agent) -> list[str]:
    return [getattr(tool, "__name__", getattr(tool, "name", "")) for tool in agent.tools]


def test_employee_data_agent_has_frozen_name_and_only_two_read_tools():
    assert set(inspect.signature(build_employee_data_agent).parameters) == {
        "model_name",
        "model_extra_config",
    }
    agent = build_employee_data_agent(
        model_name="test-model",
        model_extra_config={"extra_body": {"thinking": {"type": "disabled"}}},
    )
    assert agent.name == "hr_employee_data_agent"
    assert _tool_names(agent) == ["calc_annual_leave", "get_medical_period"]
    assert not any(word in name.lower() for name in _tool_names(agent)
                   for word in ("submit", "update", "delete", "write"))


def test_employee_data_app_does_not_import_consult_or_orchestrator():
    forbidden = ("apps.consult_agent", "apps.orchestrator")
    violations = []
    for path in APP_ROOT.rglob("*.py"):
        for target in _imports(path):
            if target.startswith(forbidden):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert not violations


def test_shared_a2a_package_contains_no_business_dependencies():
    forbidden = ("apps.", "packages.hr_domain", "veadk")
    violations = []
    for path in SHARED_A2A_ROOT.rglob("*.py"):
        for target in _imports(path):
            if target.startswith(forbidden):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert not violations


def test_employee_data_agent_card_is_frozen():
    card = build_agent_card()
    assert card.name == "hr-employee-data-agent"
    assert card.version == "1.0.0"
    assert card.protocol_version == "0.3.0"
    assert card.preferred_transport == "JSONRPC"
    assert card.url == "http://127.0.0.1:8102/"
    assert card.capabilities.streaming is True
    assert card.default_input_modes == ["text"]
    assert card.default_output_modes == ["text"]
    assert {skill.id for skill in card.skills} == {
        "employee-leave-balance-query",
        "employee-medical-period-query",
        "employee-annual-leave-calculation",
    }
