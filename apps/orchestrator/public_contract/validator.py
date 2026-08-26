"""公共合同校验器：结构与泄露检查，供静态测试与运行时复用。"""

import re

from apps.orchestrator.public_contract.capabilities import PUBLIC_CAPABILITIES
from apps.orchestrator.public_contract.contract import build_agent_contract
from apps.orchestrator.public_contract.identity import FORBIDDEN_INTERNAL_TERMS
from apps.orchestrator.public_contract.invocation_context import (
    ALLOWED_CONTEXT_KEYS,
    INVOCATION_CONTEXT_ITEMS,
)
from apps.orchestrator.public_contract.result_contract import (
    ERROR_CODES,
    RESULT_FIELDS,
)

VALID_NECESSITY = ("preferred", "accepted", "required")
# 禁止能力描述里出现函数调用式命名（Tool 化痕迹）。
TOOLISH_NAME_PATTERN = re.compile(r"^(get_|submit_|query_|create_|update_|delete_)")


def _walk_strings(value) -> "re.Iterable[tuple[str, object]]":
    if isinstance(value, str):
        yield "$", value
        return
    if isinstance(value, dict):
        for key, child in value.items():
            for child_path, leaf in _walk_strings(child):
                yield f"{child_path}.{key}", leaf
            yield "$.<key>", key
    if isinstance(value, list):
        for index, child in enumerate(value):
            for path, leaf in _walk_strings(child):
                yield f"{path}[{index}]", leaf


def validate_contract(contract: dict | None = None) -> list[str]:
    """返回违规列表；空列表表示合同通过校验。"""
    payload = contract if contract is not None else build_agent_contract()
    errors: list[str] = []

    for section in (
        "contract_version",
        "agent",
        "capabilities",
        "invocation_context",
        "interaction",
        "result_contract",
    ):
        if section not in payload:
            errors.append(f"missing_section:{section}")

    agent = payload.get("agent") or {}
    for field in ("id", "name", "version"):
        if not agent.get(field):
            errors.append(f"agent_missing:{field}")

    capabilities = payload.get("capabilities") or []
    keys = [item.get("key") for item in capabilities]
    if len(keys) != len(set(keys)):
        errors.append("capability_duplicate_key")
    expected_keys = {capability.key for capability in PUBLIC_CAPABILITIES}
    if set(keys) != expected_keys:
        errors.append("capability_set_mismatch")
    for item in capabilities:
        if TOOLISH_NAME_PATTERN.match(str(item.get("key", ""))):
            errors.append(f"capability_toolish:{item.get('key')}")
        names = item.get("name") or {}
        if not (names.get("zh-CN") and names.get("en")):
            errors.append(f"capability_name_incomplete:{item.get('key')}")

    context_items = payload.get("invocation_context") or []
    context_keys = [item.get("key") for item in context_items]
    if set(context_keys) != set(ALLOWED_CONTEXT_KEYS):
        errors.append("invocation_context_set_mismatch")
    for item in context_items:
        if item.get("necessity") not in VALID_NECESSITY:
            errors.append(f"context_invalid_necessity:{item.get('key')}")
        applies_to = item.get("applies_to") or []
        unknown = set(applies_to) - expected_keys
        if unknown:
            errors.append(f"context_unknown_applies_to:{sorted(unknown)}")

    interaction = payload.get("interaction") or {}
    for flag in (
        "streaming_transport",
        "incremental_content",
        "input_required",
        "resume",
        "cancel",
        "durable_task_recovery",
    ):
        if not isinstance(interaction.get(flag), bool):
            errors.append(f"interaction_flag_not_bool:{flag}")

    result_contract = payload.get("result_contract") or {}
    if set(result_contract.get("fields") or []) != set(RESULT_FIELDS):
        errors.append("result_fields_mismatch")
    if set(result_contract.get("error_codes") or []) != set(ERROR_CODES):
        errors.append("error_codes_mismatch")

    for path, value in _walk_strings(payload):
        for term in FORBIDDEN_INTERNAL_TERMS:
            if term in str(value):
                errors.append(f"internal_term_leak:{path}:{term}")

    return errors
