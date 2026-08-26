"""机器可读公共智能体合同 /.well-known/agent-contract.json 的唯一生成源。

必须由代码生成，不允许手工维护一份与运行代码无关系的JSON。
"""

import hashlib
import json

from apps.orchestrator.public_contract.capabilities import capabilities_payload
from apps.orchestrator.public_contract.identity import (
    PUBLIC_AGENT_ID,
    PUBLIC_AGENT_NAME_EN,
    PUBLIC_AGENT_NAME_ZH,
    PUBLIC_AGENT_VERSION,
)
from apps.orchestrator.public_contract.interaction import interaction_payload
from apps.orchestrator.public_contract.invocation_context import (
    invocation_context_payload,
)
from apps.orchestrator.public_contract.result_contract import (
    result_contract_payload,
)

CONTRACT_VERSION = "1.0.0"


def build_agent_contract() -> dict:
    """构造完整公共智能体合同（纯函数，可重复生成）。"""
    return {
        "contract_version": CONTRACT_VERSION,
        "agent": {
            "id": PUBLIC_AGENT_ID,
            "name": {"zh-CN": PUBLIC_AGENT_NAME_ZH, "en": PUBLIC_AGENT_NAME_EN},
            "version": PUBLIC_AGENT_VERSION,
        },
        "capabilities": capabilities_payload(),
        "invocation_context": invocation_context_payload(),
        "interaction": interaction_payload(),
        "result_contract": result_contract_payload(),
    }


def contract_digest(contract: dict | None = None) -> str:
    """合同规范化摘要，用于注册与破坏性变更检测。"""
    payload = contract if contract is not None else build_agent_contract()
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
