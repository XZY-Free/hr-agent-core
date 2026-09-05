"""生成SnowHarness注册包（阶段2：契约导入 + 运行时注册请求）。

产物是确定性的工件构造，不在生成过程中运行测试或制造自证报告：
- agent-card.example.json（静态示例，非live authority；live AgentCard只能
  通过 HTTP discovery GET /.well-known/agent-card.json 获取）
- agent-contract.json
- runtime-registration.example.json（capability-driven conformance schema）
- snowharness-registration.md（operator runbook）

用法：.venv/bin/python scripts/generate_snowharness_registration.py \
    [--base-url https://hr-assistant.example.invalid] \
    [--output artifacts/snowharness-registration]
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
EXAMPLE_BASE_URL = "https://hr-assistant.example.invalid"

# Snow端点请求体占位符：明确非秘密，由管理员导入合同后替换为真实ID。
CONTRACT_SNAPSHOT_PLACEHOLDER = "<contract_snapshot_id-from-contract-import>"
# 固定示例输入：必须与真实Provider测试证明能产生的预期状态一致
# （tests/contract/test_snowharness_registration.py）。
# basic → completed
CONFORMANCE_BASIC_INPUT = "公司年休假的基本规则是什么？"
# input_required → input-required
CONFORMANCE_INPUT_REQUIRED_INPUT = "我想请假"
# resume: start → input-required, resume → 补充信息（不含确认/提交）
CONFORMANCE_RESUME_START_INPUT = "我想请年假"
CONFORMANCE_RESUME_RESUME_INPUT = "明天一天"


def _runtime_registration(base_url: str) -> dict:
    """构造与Snow运行时注册端点一致的请求体。

    conformance schema是capability-driven的：HR Contract声明
    streaming=true / incremental=false / inputRequired=true / resume=true /
    cancel=false / durable=false，因此注册 basic、input_required、resume；
    cancel不受支持，不包含cancel探针。
    """
    return {
        "contract_snapshot_id": CONTRACT_SNAPSHOT_PLACEHOLDER,
        "runtime_endpoint": f"{base_url.rstrip('/')}/",
        "authentication": {"mode": "none", "credential_ref_id": None},
        "conformance": {
            "basic": {"input": CONFORMANCE_BASIC_INPUT},
            "input_required": {"input": CONFORMANCE_INPUT_REQUIRED_INPUT},
            "resume": {
                "start_input": CONFORMANCE_RESUME_START_INPUT,
                "resume_input": CONFORMANCE_RESUME_RESUME_INPUT,
            },
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
    return f"""# SnowHarness 注册说明（Operator Runbook）— {PUBLIC_AGENT_NAME_ZH}

- 稳定身份：`{PUBLIC_AGENT_ID}`（公共版本 `{PUBLIC_AGENT_VERSION}`）
- 协议：A2A 0.3.0（JSON-RPC over HTTP，SSE流式事件通道）
- 交互能力（与运行时一致，不得漂移）：
  `streaming=true, incremental=false, inputRequired=true, resume=true,
  cancel=false, durable=false`
- 静态示例端点：`{runtime_endpoint}`（仅示例；live AgentCard只能HTTP discovery）

## 能力摘要（任务领域，非函数列表）

| 稳定键 | 名称 |
|---|---|
{capabilities_table}

## 调用上下文合同摘要

| 上下文 | 必要性 |
|---|---|
{context_table}

执行主体（execution_subject）只含 `subject_id` + `subject_kind`
（`platform_user` / `platform_service`），不传 employee_id / corp_id /
任何内部凭据；身份映射在智能体私有层完成，未验证身份返回稳定
`identity_unverified`。

## Operator 注册步骤

1. **启动 Public A2A**：设置
   `HR_ASSISTANT_A2A_HOST/PORT/PUBLIC_URL/AUTH_MODE`（见 `.env.example`）
   并启动 hr-assistant 公共A2A进程。
2. **health**：`GET <public_url>/health` 确认
   `status/agent/version/protocol_version/auth_mode`。
3. **live AgentCard**：`GET <public_url>/.well-known/agent-card.json`。
   `card.url` 就是JSON-RPC端点；SnowHarness 的 `runtime_endpoint`
   与 `card.url` 规范化后必须一致。静态 `agent-card.example.json`
   不是live authority。
4. **导入agent-contract**：管理员将 `agent-contract.json` 作为一次性
   请求输入导入SnowHarness，得到 `contract_snapshot_id`。
5. **AgentRevision**：在SnowHarness中基于导入的合同创建AgentRevision。
6. **Runtime Registration**：把 `runtime-registration.example.json` 中
   `{snapshot_placeholder}` 替换为真实ID，`runtime_endpoint` 替换为
   live `card.url`，认证按实际配置填写后提交。
7. **Publication**：发布该AgentRevision/RuntimeRevision。
8. **Route**：在SnowHarness中配置Route/ExecutionBinding与允许的
   Invocation Context。
9. **Employee选择**：员工在SnowHarness中选择该Agent发起会话。
10. **input-required/resume**：用 `conformance` 固定输入验证
    input-required 与 same task/context resume。
11. **取消不受支持**：公共 Orchestrator 不暴露 `tasks/cancel`；任何取消请求
    都会被 A2A `UnsupportedOperationError`(-32004) 拒绝，任务状态不变。
    resume（同 task/context 续发补充）仍按第10步验证。
12. **bearer可选**：`HR_ASSISTANT_A2A_AUTH_MODE=bearer` 时必须配置
    `HR_ASSISTANT_A2A_BEARER_TOKEN`，并在SnowHarness用CredentialRef
    引用凭据；禁止把真实token写进任何工件或git。

## Subject → 内部映射（operator私下操作）

- HR侧用 `scripts/public_subject_ref.py --subject-kind platform_user
  --subject-id <snow-subject-id>` 计算 internal_user_id；
- 管理员私下在 `EMPLOYEE_IDENTITY_MAP_JSON` 配置
  `internal_user_id → employeeId`；
- SnowHarness永不拥有employeeId，也不得保存/传递。

运行时不提供远程合同端点；`agent-contract.json` 只通过上述导入步骤
进入SnowHarness。本包不附带任何由提供方生成的测试结论。
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
        ("agent-card.example.json", card_payload),
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
    # 只返回本次生成的四个产物；旧 agent-card.json 由调用方删除，不留双文件。
    return sorted(written)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=EXAMPLE_BASE_URL,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    files = generate(arguments.base_url, arguments.output)
    for path in files:
        print(path.resolve().relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
