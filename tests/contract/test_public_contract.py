"""批次1：公共智能体合同静态测试。"""

from apps.orchestrator.public_contract.capabilities import PUBLIC_CAPABILITIES
from apps.orchestrator.public_contract.contract import (
    build_agent_contract,
    contract_digest,
)
from apps.orchestrator.public_contract.identity import (
    PUBLIC_AGENT_ID,
    PUBLIC_AGENT_NAME_ZH,
    PUBLIC_AGENT_VERSION,
)
from apps.orchestrator.public_contract.interaction import (
    CANCEL,
    DURABLE_TASK_RECOVERY,
    INCREMENTAL_CONTENT,
    INPUT_REQUIRED,
    STREAMING_TRANSPORT,
)
from apps.orchestrator.public_contract.validator import validate_contract


def test_contract_structure_and_no_leak():
    errors = validate_contract()
    assert errors == []


def test_public_identity_stable():
    contract = build_agent_contract()
    agent = contract["agent"]
    assert agent["id"] == PUBLIC_AGENT_ID == "hr-assistant"
    assert agent["name"]["zh-CN"] == PUBLIC_AGENT_NAME_ZH == "企业人力智能助手"
    assert agent["version"] == PUBLIC_AGENT_VERSION == "1.0.0"
    assert contract["contract_version"] == "1.0.0"


def test_capabilities_are_task_domains_not_tools():
    contract = build_agent_contract()
    keys = [item["key"] for item in contract["capabilities"]]
    assert keys == [capability.key for capability in PUBLIC_CAPABILITIES]
    assert keys == [
        "leave-and-attendance-service",
        "employee-self-service",
        "hr-policy-and-benefits-consultation",
        "hr-system-and-document-assistance",
    ]
    # 能力键/描述不得出现函数式命名。
    serialized = repr(contract["capabilities"])
    for toolish in ("submit_leave", "get_schedule", "get_leave_balance"):
        assert toolish not in serialized


def test_invocation_context_is_agent_level_contract():
    contract = build_agent_contract()
    items = {item["key"]: item for item in contract["invocation_context"]}
    assert set(items) == {
        "execution_subject",
        "timezone",
        "current_datetime",
        "locale",
        "conversation_summary",
        "attachment_references",
    }
    # 第一版不出现全局 required；附件引用为 accepted。
    assert items["execution_subject"]["necessity"] == "preferred"
    assert items["timezone"]["necessity"] == "preferred"
    assert items["current_datetime"]["necessity"] == "preferred"
    assert items["locale"]["necessity"] == "preferred"
    assert items["conversation_summary"]["necessity"] == "preferred"
    assert items["attachment_references"]["necessity"] == "accepted"
    assert items["execution_subject"]["applies_to"] == [
        "leave-and-attendance-service",
        "employee-self-service",
    ]


def test_interaction_flags_are_honest():
    contract = build_agent_contract()
    interaction = contract["interaction"]
    assert interaction["streaming_transport"] is STREAMING_TRANSPORT is True
    assert interaction["incremental_content"] is INCREMENTAL_CONTENT is False
    assert interaction["input_required"] is INPUT_REQUIRED is True
    assert interaction["cancel"] is CANCEL is False
    assert (
        interaction["durable_task_recovery"] is DURABLE_TASK_RECOVERY is False
    )
    # 真实运行时支持同一task/context续发，合同必须显式声明resume。
    assert interaction["resume"] is True
    assert interaction["supported_locales"] == ["zh-CN"]


def test_interaction_resume_must_be_explicit_boolean():
    """resume是SnowHarness严格解析的六个显式布尔之一：
    缺失、null、非布尔都必须被校验器拒绝。"""
    missing = build_agent_contract()
    del missing["interaction"]["resume"]
    assert "interaction_flag_not_bool:resume" in validate_contract(missing)

    for bad in (None, "true", 1):
        tampered = build_agent_contract()
        tampered["interaction"]["resume"] = bad
        assert "interaction_flag_not_bool:resume" in validate_contract(tampered)


def test_result_contract_fields_and_error_codes():
    contract = build_agent_contract()
    result_contract = contract["result_contract"]
    assert set(result_contract["fields"]) == {
        "request_id",
        "status",
        "answer",
        "result_type",
        "data",
        "actions",
        "error_code",
        "retryable",
        "agent_name",
        "agent_version",
    }
    assert set(result_contract["error_codes"]) == {
        "identity_required",
        "identity_unverified",
        "input_required",
        "not_found",
        "rejected",
        "temporarily_unavailable",
        "failed",
        "cancelled",
        "contract_error",
    }


def test_contract_digest_stable_and_breaking_change_detected():
    first = build_agent_contract()
    second = build_agent_contract()
    assert contract_digest(first) == contract_digest(second)

    tampered = build_agent_contract()
    tampered["agent"]["version"] = "2.0.0"
    assert contract_digest(tampered) != contract_digest(first)


def test_validator_catches_leak_and_toolish_capability():
    leaky = build_agent_contract()
    leaky["agent"]["description"] = "powered by root_agent and veADK"
    errors = validate_contract(leaky)
    assert any("internal_term_leak" in error for error in errors)

    toolish = build_agent_contract()
    toolish["capabilities"][0]["key"] = "submit_leave"
    errors = validate_contract(toolish)
    assert "capability_toolish:submit_leave" in errors
    assert "capability_set_mismatch" in errors


def test_cancel_unsupported_but_durable_recovery_not_claimed():
    """公共任务以 UnsupportedOperation 拒绝 tasks/cancel；进程内TaskStore不能宣称持久恢复。"""
    from apps.orchestrator.public_a2a.card import build_agent_card

    contract = build_agent_contract()
    assert contract["interaction"]["cancel"] is False
    assert contract["interaction"]["durable_task_recovery"] is False

    card = build_agent_card("https://hr-assistant.example.invalid")
    serialized = card.model_dump_json(by_alias=True, exclude_none=True)
    assert "cancellation" not in serialized.lower()
