"""批次8：SnowHarness注册包生成契约测试。

不变式：注册包是"运营方导入的合同工件 + 独立的运行时注册请求"，
绝不让SnowHarness去黑盒运行时发现/拉取合同，也不附带自证式
conformance报告。生成器是确定性产物构造，不是证据制造。
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from apps.orchestrator.public_contract.contract import build_agent_contract
from apps.orchestrator.public_contract.validator import validate_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_snowharness_registration.py"
BASE_URL = "https://hr-assistant.example.invalid"

EXPECTED_FILES = {
    "agent-card.json",
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

SECRET_MARKERS = ("bearer", "secret", "password", "api_key", "credential_ref_id=")


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


def test_runtime_registration_matches_snow_endpoint_schema(generated):
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
    # 占位符须明确非秘密；runtime_endpoint来自base_url。
    assert isinstance(registration["contract_snapshot_id"], str)
    assert registration["contract_snapshot_id"]
    assert registration["runtime_endpoint"] == f"{BASE_URL}/"
    # 当前公共服务无bearer强制，示例必须诚实使用none/null。
    assert registration["authentication"] == {
        "mode": "none",
        "credential_ref_id": None,
    }
    # 安全的conformance输入；resume是补充信息，不是确认/提交。
    assert registration["conformance"] == {
        "start_input": "我想请假",
        "resume_input": "年休假，明天一天",
    }
    assert "确认" not in registration["conformance"]["resume_input"]
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


def test_markdown_imports_contract_then_registers_runtime(generated):
    markdown = (generated / "snowharness-registration.md").read_text(
        encoding="utf-8"
    )
    low = markdown.lower()
    for phrase in FORBIDDEN_MARKDOWN_PHRASES:
        assert phrase.lower() not in low, phrase
    # 两步说明：先导入合同工件获得结构化ID，再提交运行时注册。
    assert "导入" in markdown
    assert "runtime-registration" in markdown
    assert "contract_snapshot_id" in markdown
    # 主动Conformance期间只拉取标准AgentCard，不做合同发现。
    assert "AgentCard" in markdown


def test_generated_artifacts_contain_no_secrets(generated):
    for path in generated.iterdir():
        content = path.read_text(encoding="utf-8").lower()
        for marker in SECRET_MARKERS:
            assert marker not in content, (path.name, marker)


def test_generation_must_not_invoke_subprocess(monkeypatch, tmp_path):
    """生成器是确定性产物构造：不允许在生成过程中起测试子进程。
    先打桩标准库subprocess模块再加载生成器——Python返回同一模块对象，
    生成器未来若import/使用subprocess同样会被拦截。"""
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
    # 与代码生成源一致，非手工维护副本。
    assert contract == build_agent_contract()
