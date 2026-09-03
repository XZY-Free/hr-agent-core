"""阶段2 Track H：SnowHarness注册包生成契约测试。

不变式：注册包是"运营方导入的合同工件 + 独立的运行时注册请求"，
绝不让SnowHarness去黑盒运行时发现/拉取合同，也不附带自证式
conformance报告。生成器是确定性产物构造，不是证据制造。

阶段2新增：静态Card只以 example 形态存在（唯一live authority是HTTP
discovery）；conformance schema是capability-driven的，HR contract
cancel=true 因此必须包含cancel探针。
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from apps.orchestrator.public_contract.contract import build_agent_contract
from apps.orchestrator.public_contract.interaction import (
    CANCEL,
    INPUT_REQUIRED,
    RESUME,
    STREAMING_TRANSPORT,
)
from apps.orchestrator.public_contract.validator import validate_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_snowharness_registration.py"
BASE_URL = "https://hr-assistant.example.invalid"

EXPECTED_FILES = {
    "agent-card.example.json",
    "agent-contract.json",
    "runtime-registration.example.json",
    "snowharness-registration.md",
}

FORBIDDEN_MARKDOWN_PHRASES = (
    "passed=true",
    "passed = true",
    "contract-test-report",
    "agent_contract_url",
    "agent_card_url",
    "合同发现",
    "发现合同",
    "Provider报告",
    "已记录报告",
)

# 禁止的是秘密值本身：bearer一词作为运行方式说明允许出现在runbook，
# 但任何真实token/带值字段不得进入工件。
SECRET_MARKERS = (
    "authorization: bearer ",
    "hr_assistant_a2a_bearer_token=",
    "password",
    "api_key",
)


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_snowharness_registration", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ForbiddenSubprocess:
    def __call__(self, *args, **kwargs):
        raise AssertionError("generation must not invoke subprocess")


@pytest.fixture
def generated(tmp_path):
    module = _load_generator()
    module.generate(BASE_URL, tmp_path)
    return tmp_path


def test_generated_file_set_is_exactly_four(generated):
    names = {path.name for path in generated.iterdir()}
    assert names == EXPECTED_FILES


def test_static_card_is_example_only(generated):
    """静态Card只能是example：live AgentCard唯一Authority是HTTP discovery。"""
    card = json.loads(
        (generated / "agent-card.example.json").read_text(encoding="utf-8")
    )
    assert card["url"].startswith("https://hr-assistant.example.invalid")
    assert card["protocolVersion"] == "0.3.0"
    assert card["preferredTransport"] == "JSONRPC"
    assert card["capabilities"]["streaming"] is True
    # 旧文件名不得回潮（不留双文件兼容）。
    assert not (generated / "agent-card.json").exists()


def test_runtime_registration_matches_capability_driven_schema(generated):
    registration = json.loads(
        (generated / "runtime-registration.example.json").read_text(
            encoding="utf-8"
        )
    )
    # 顶层键必须与Snow端点请求体一致，不复制身份/能力/摘要/URL。
    assert set(registration) == {
        "contract_snapshot_id",
        "runtime_endpoint",
        "authentication",
        "conformance",
    }
    assert registration["runtime_endpoint"] == f"{BASE_URL}/"
    # 默认example诚实使用none/null；bearer由operator在runbook指引下单独配置。
    assert registration["authentication"] == {
        "mode": "none",
        "credential_ref_id": None,
    }
    conformance = registration["conformance"]
    assert set(conformance) == {"basic", "input_required", "resume", "cancel"}
    assert conformance["cancel"] == {"input": "我想请假"}
    assert conformance["basic"] == {"input": "公司年休假的基本规则是什么？"}
    assert conformance["input_required"] == {"input": "我想请假"}
    assert conformance["resume"] == {
        "start_input": "我想请年假",
        "resume_input": "明天一天",
    }
    assert "确认" not in conformance["resume"]["resume_input"]
    serialized = json.dumps(registration, ensure_ascii=False)
    for forbidden in (
        "agent_card_url",
        "agent_contract_url",
        "passed",
        "report",
        "capabilities",
        "digest",
    ):
        assert forbidden not in serialized, forbidden


def test_conformance_schema_consistent_with_interaction_contract(generated):
    """conformance探针集合必须由interaction合同驱动，不得漂移。"""
    assert STREAMING_TRANSPORT is True
    assert INPUT_REQUIRED is True
    assert RESUME is True
    assert CANCEL is True
    registration = json.loads(
        (generated / "runtime-registration.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert "cancel" in registration["conformance"]


def test_markdown_is_operator_runbook(generated):
    markdown = (generated / "snowharness-registration.md").read_text(
        encoding="utf-8"
    )
    low = markdown.lower()
    for phrase in FORBIDDEN_MARKDOWN_PHRASES:
        assert phrase.lower() not in low, phrase
    # operator runbook关键步骤。
    assert "导入" in markdown
    assert "runtime-registration" in markdown
    assert "contract_snapshot_id" in markdown
    assert "AgentCard" in markdown
    assert "discovery" in markdown
    assert "cancel=true" in markdown
    assert "bearer" in markdown  # runbook单独说明bearer配置，但无真实token
    # 不写SnowHarness内部源码路径。
    assert "src/" not in markdown
    assert "packages/" not in markdown


def test_generated_artifacts_contain_no_secrets(generated):
    for path in generated.iterdir():
        content = path.read_text(encoding="utf-8").lower()
        for marker in SECRET_MARKERS:
            assert marker not in content, (path.name, marker)


def test_generation_must_not_invoke_subprocess(monkeypatch, tmp_path):
    """生成器是确定性产物构造：不允许在生成过程中起测试子进程。"""
    forbidden = _ForbiddenSubprocess()
    for name in ("run", "Popen", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    module = _load_generator()
    files = module.generate(BASE_URL, tmp_path)
    assert {path.name for path in files} == EXPECTED_FILES


def test_contract_artifact_passes_validator_with_resume(generated):
    contract = json.loads(
        (generated / "agent-contract.json").read_text(encoding="utf-8")
    )
    assert validate_contract(contract) == []
    assert contract["interaction"]["resume"] is True
    assert contract["interaction"]["cancel"] is True
    # 与代码生成源一致，非手工维护副本。
    assert contract == build_agent_contract()


def test_fixed_conformance_inputs_match_plan(generated):
    """阶段2方案05§5固定示例输入，静态示例必须有真实Provider test证明。"""
    from apps.orchestrator.public_contract.interaction import interaction_payload

    registration = json.loads(
        (generated / "runtime-registration.example.json").read_text(
            encoding="utf-8"
        )
    )
    conformance = registration["conformance"]
    # 真实证明位于 tests/e2e/test_hr_assistant_a2a_protocol.py
    # （basic→completed、我想请假/我想请年假→input-required、resume→终态）。
    assert conformance["basic"]["input"] == "公司年休假的基本规则是什么？"
    assert conformance["input_required"]["input"] == "我想请假"
    assert conformance["resume"]["start_input"] == "我想请年假"
    assert conformance["resume"]["resume_input"] == "明天一天"
    _ = interaction_payload  # interaction合同保持代码生成源
