"""批次2单仓多应用结构门禁。"""

import ast
import hashlib
import importlib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_NAMES = {"orchestrator", "consult_agent", "employee_data_agent", "leave_agent"}


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py")) if root.exists() else []


def _import_targets(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def test_frozen_application_and_domain_directories_exist():
    expected = {
        "apps/orchestrator",
        "apps/orchestrator/local_leave",
        "apps/consult_agent",
        "apps/employee_data_agent",
        "apps/leave_agent",
        "packages/hr_domain/constants",
        "packages/hr_domain/schemas",
        "packages/hr_domain/rules",
        "packages/hr_domain/gaia",
        "deployment/environments/dev",
        "deployment/environments/staging",
        "deployment/environments/prod",
        "tests/unit",
        "tests/contract",
        "tests/eval",
        "tests/integration",
        "tests/e2e",
    }
    missing = sorted(path for path in expected if not (REPO_ROOT / path).is_dir())
    assert not missing, f"缺少冻结目录：{missing}"


def test_apps_do_not_import_other_apps():
    violations = []
    apps_root = REPO_ROOT / "apps"
    for path in _python_files(apps_root):
        relative = path.relative_to(apps_root)
        owner = relative.parts[0]
        for target in _import_targets(path):
            if not target.startswith("apps."):
                continue
            target_app = target.split(".")[1]
            if target_app != owner:
                violations.append(f"{relative}: {target}")
    assert not violations, "应用间直接导入：" + ", ".join(violations)


def test_hr_domain_has_no_app_or_agent_framework_dependency():
    violations = []
    domain_root = REPO_ROOT / "packages" / "hr_domain"
    for path in _python_files(domain_root):
        relative = path.relative_to(REPO_ROOT)
        imports = _import_targets(path)
        forbidden = sorted(
            target for target in imports
            if target == "apps" or target.startswith("apps.")
            or target == "veadk" or target.startswith("veadk.")
            or target == "agentkit" or target.startswith("agentkit.")
        )
        if forbidden:
            violations.append(f"{relative}: {forbidden}")
        text = path.read_text(encoding="utf-8")
        if "_AGENT_PROMPT" in text or "Agent(" in text:
            violations.append(f"{relative}: Agent或提示词资产")
    assert not violations, "hr_domain边界违规：" + ", ".join(violations)


def test_local_python_import_graph_has_no_cycles():
    roots = (REPO_ROOT / "apps", REPO_ROOT / "packages")
    files = [path for root in roots for path in _python_files(root)]
    modules = {_module_name(path): path for path in files}
    graph = {
        module: {
            target for target in _import_targets(path)
            if target in modules and target != module
        }
        for module, path in modules.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(module: str):
        if module in visiting:
            cycle = visiting[visiting.index(module):] + [module]
            raise AssertionError("循环依赖：" + " -> ".join(cycle))
        if module in visited:
            return
        visiting.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        visiting.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)


def test_root_entry_assembles_a2a_only_orchestrator():
    compatibility = importlib.import_module("agent")
    assert compatibility.root_agent.name == "root_agent"
    assert compatibility.leave_agent.name == "leave_agent"
    assert any(agent is compatibility.leave_agent for agent in compatibility.root_agent.sub_agents)
    assert not hasattr(compatibility, "consult_agent")
    assert not hasattr(compatibility, "employee_data_tools")
    assert compatibility.agent_server_app.app is not None


def test_orchestrator_keeps_only_leave_and_page_jump_local():
    from agent import build_agent_application

    application = build_agent_application(a2a_client=object())
    tool_names = [
        getattr(tool, "__name__", getattr(tool, "name", ""))
        for tool in application.root_agent.tools
    ]
    assert tool_names == ["page_jump"]
    assert [agent.name for agent in application.root_agent.sub_agents] == ["leave_agent"]
    assert application.remote_router is not None


def test_cloud_a2a_mode_binds_each_runtime_key_to_its_registered_url(monkeypatch):
    from agent import build_agent_application

    consult_url = "https://consult.example.invalid"
    employee_url = "https://employee.example.invalid"
    monkeypatch.setenv("HR_CONSULT_A2A_URL", consult_url)
    monkeypatch.setenv("HR_EMPLOYEE_DATA_A2A_URL", employee_url)
    monkeypatch.setenv("HR_CONSULT_RUNTIME_API_KEY", "consult-runtime-key")
    monkeypatch.setenv("HR_EMPLOYEE_DATA_RUNTIME_API_KEY", "employee-runtime-key")

    application = build_agent_application()

    assert application.remote_router.client.runtime_api_keys == {
        consult_url: "consult-runtime-key",
        employee_url: "employee-runtime-key",
    }


def test_agent_tools_and_prompt_content_are_frozen():
    compatibility = importlib.import_module("agent")
    tool_names = lambda value: [
        getattr(tool, "__name__", getattr(tool, "name", ""))
        for tool in value.tools
    ]
    assert tool_names(compatibility.root_agent) == ["page_jump"]
    assert tool_names(compatibility.leave_agent) == [
        "get_leave_permissions", "get_leave_balance", "get_schedule", "submit_leave"
    ]

    prompts = {
        "apps.orchestrator.prompts": (
            "MAIN_AGENT_PROMPT",
            # 批次2公共契约化：新增【执行上下文】可信日期时间说明行。
            "70b50b114ddda39558fdce917319365b31d53ef676c422bd3b563777ecd8c682",
        ),
        "apps.orchestrator.local_leave.prompts": (
            "LEAVE_AGENT_PROMPT",
            # 批次2公共契约化：新增【执行上下文】可信日期时间说明行。
            "a77fbbfbe086cc5e246d7ba607950d6895f44c9cb604d0baa562a846424e54e5",
        ),
        "apps.consult_agent.prompts": (
            "CONSULT_AGENT_PROMPT",
            "713ad2073084969710e498f4ec4d9df3d75ddca668a3169ceccef8da763084b5",
        ),
    }
    for module_name, (attribute, expected_hash) in prompts.items():
        value = getattr(importlib.import_module(module_name), attribute)
        assert hashlib.sha256(value.encode()).hexdigest() == expected_hash


def test_all_21_evaluation_cases_remain():
    cases = yaml.safe_load((REPO_ROOT / "tests/eval/cases.yaml").read_text())
    assert len(cases) == 21
    assert len({case["id"] for case in cases}) == 21
    followup = next(case for case in cases if case["id"] == "followup_present")
    assert followup["quality_keywords"] == ["还想了解"]


def test_old_hr_agent_tree_and_forbidden_version_directories_are_absent():
    assert not (REPO_ROOT / "hr_agent").exists()
    forbidden = {"v2", "v3", "new", "legacy", "temp", "a2a_v1"}
    violations = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.rglob("*")
        if path.is_dir() and path.name in forbidden
        and ".venv" not in path.parts and ".git" not in path.parts
    )
    assert not violations, f"禁止目录：{violations}"
