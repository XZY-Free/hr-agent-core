"""生成SnowHarness注册包（批次8：契约导入 + 运行时注册请求）。

产物是确定性的工件构造，不在生成过程中运行测试或制造自证报告：
- agent-card.json
- agent-contract.json
- runtime-registration.example.json
- snowharness-registration.md

用法：.venv/bin/python scripts/generate_snowharness_registration.py \
    --base-url https://hr-assistant.example.invalid [--output artifacts/snowharness-registration]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.orchestrator.public_a2a.card import build_agent_card  # noqa: E402
from apps.orchestrator.public_contract.contract import (  # noqa: E402
    build_agent_contract,
)
from apps.orchestrator.public_contract.identity import (  # noqa: E402
    PUBLIC_AGENT_ID,
    PUBLIC_AGENT_NAME_ZH,
    PUBLIC_AGENT_VERSION,
)
from apps.orchestrator.public_contract.validator import (  # noqa: E402
    validate_contract,
)

DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "snowharness-registration"

# Snow端点请求体占位符：明确非秘密，由管理员导入合同后替换为真实ID。
CONTRACT_SNAPSHOT_PLACEHOLDER = "<contract_snapshot_id-from-contract-import>"
# 安全的Conformance输入：start触发input-required；resume为补充信息，
# 绝不是"确认"，不会造成提交。
CONFORMANCE_START_INPUT = "我想请假"
CONFORMANCE_RESUME_INPUT = "年休假，明天一天"


def _runtime_registration(base_url: str) -> dict:
    """构造与Snow运行时注册端点一致的请求体。

    不复制智能体身份、能力、合同摘要或任何发现URL：
    身份与能力属于已导入的合同快照，运行时端点才是本次注册的新事实。
    当前公共服务未强制bearer认证，示例必须诚实地使用none/null。
    """
    return {
        "contract_snapshot_id": CONTRACT_SNAPSHOT_PLACEHOLDER,
        "runtime_endpoint": f"{base_url.rstrip('/')}/",
        "authentication": {"mode": "none", "credential_ref_id": None},
        "conformance": {
            "start_input": CONFORMANCE_START_INPUT,
            "resume_input": CONFORMANCE_RESUME_INPUT,
        },
    }


def _markdown(contract: dict, registration: dict) -> str:
    runtime_endpoint = registration["runtime_endpoint"]
    snapshot_placeholder = registration["contract_snapshot_id"]
    capabilities_table = "\n".join(
        f"| `{cap['key']}` | {cap['name']['zh-CN']} |"
        for cap in contract["capabilities"]
    )
    context_table = "\n".join(
        f"| `{item['key']}` | {item['necessity']} |"
        for item in contract["invocation_context"]
    )
    return f"""# SnowHarness 注册说明 — {PUBLIC_AGENT_NAME_ZH}

- 稳定身份：`{PUBLIC_AGENT_ID}`（公共版本 `{PUBLIC_AGENT_VERSION}`）
- Runtime 端点：`{runtime_endpoint}`
- 协议：A2A 0.3.0（JSON-RPC over HTTP，SSE流式事件通道）
- 认证方式：当前为 none（无强制认证；接入方按运行时实际配置填写）

## 能力摘要（任务领域，非函数列表）

| 稳定键 | 名称 |
|---|---|
{capabilities_table}

## 调用上下文合同摘要

| 上下文 | 必要性 |
|---|---|
{context_table}

执行主体（execution_subject）不传 employee_id / corp_id / 任何内部凭据；
身份映射由智能体内部完成，未验证身份返回稳定 `identity_unverified`。

## 注册步骤

1. **导入合同工件**：管理员将 `agent-contract.json` 作为一次性请求输入
   导入SnowHarness。SnowHarness解析后以结构化字段（身份、能力、
   交互声明、结果合同等）存入数据库并返回 `contract_snapshot_id`；
   原始合同文件是瞬时输入，SnowHarness不整体存储该文件，也不需要
   再次读取它。
2. **提交运行时注册**：运营方将 `runtime-registration.example.json` 中
   的占位符 `{snapshot_placeholder}` 替换为上一步返回的真实ID，
   填入实际 `runtime_endpoint` 与认证配置后提交。
3. **执行Conformance**：SnowHarness主动调用运行时，期间只拉取标准
   AgentCard（`/.well-known/agent-card.json`）作为协议证据，按
   `conformance` 输入执行真实对话验证（start触发补充信息提示，
   resume为补充说明文本，不含确认或提交动作）。

运行时不提供远程合同端点；`agent-contract.json` 只通过上述导入步骤
进入SnowHarness，不由平台从运行时拉取。本包不附带任何由提供方
生成的测试结论。
"""


def generate(base_url: str, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)

    card = build_agent_card(base_url)
    contract = build_agent_contract()
    errors = validate_contract(contract)
    if errors:
        raise SystemExit(f"公共合同校验失败:{errors}")

    registration = _runtime_registration(base_url)

    written = []
    card_payload = card.model_dump(mode="json", by_alias=True, exclude_none=True)
    for name, payload in (
        ("agent-card.json", card_payload),
        ("agent-contract.json", contract),
        ("runtime-registration.example.json", registration),
    ):
        path = output / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)

    markdown_path = output / "snowharness-registration.md"
    markdown_path.write_text(
        _markdown(contract, registration), encoding="utf-8"
    )
    written.append(markdown_path)
    # 只返回本次生成的四个产物；输出目录中的历史遗留文件由人工清理。
    return sorted(written)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="https://hr-assistant.example.invalid",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    files = generate(arguments.base_url, arguments.output)
    for path in files:
        print(path.resolve().relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
