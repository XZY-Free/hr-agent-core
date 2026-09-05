"""WP-01 公共身份远端验收：一个不变量。

一个公共执行主体只能访问自己被映射到的那一个 HR 身份，且这条映射在公共部署的
Orchestrator 与部署的 Employee Data 上保持一致。

范围：真实 HTTPS A2A 调用（三个 AgentKit 开发 Runtime）。无本地应用/模型/服务、
无 fake-model、无 ASGI。身份判定只依赖服务端真实行为；不接受匿名/未映射被当成
成功业务结果，也不把服务不可用当成预期业务结果。每个测试都必须实际调用云端。

安全：本文件不改任何生产代码；敏感断言全部走 business_support._check()，避免 pytest
断言内省打印主体/oracle/ref 原始值；不打印凭据/env/oracle。期望 employee_ref 与
medical_period 数值由操作方 root 通过 HR_ACCEPTANCE_IDENTITY_ORACLE_JSON 注入。
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 请假录入 / 免同意只读词面（不提交事务、不依赖余额行）。
LEAVE_INTRO = "我想请年假"
LEAVE_FULL = "我要请2026年9月10日一天年假，请先核对我的请假权限"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    # 校验（唯一、双主体、ref 唯一、医疗余额互异）在装入期完成，失败即整体失败。
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


@pytest.fixture(scope="session")
def subject_b(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[1]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


def _unmapped_subject() -> dict:
    return {"subject_id": f"snow-unmapped-{uuid4().hex[:12]}", "subject_kind": bs.USER_KIND}


# --------------------------------------------------------------------------
# 复用断言（generic message；不打印秘密值；每条都含期望的精确状态）
# --------------------------------------------------------------------------
def _assert_identity_unverified(data: dict, label: str) -> None:
    bs._check(data.get("status") == "rejected", f"{label}本人数据访问未被拒绝")
    bs._check(data.get("error_code") == bs.ERROR_IDENTITY_UNVERIFIED, f"{label}未返回 identity_unverified")


def _assert_rejected_outcome(data: dict, label: str) -> None:
    """null/零值属于非法主体结构，必须返回合同错误。"""
    bs._check(data.get("status") == "failed", f"{label}未被拒绝")
    bs._check(
        data.get("error_code") == "contract_error",
        f"{label}未返回精确合同/身份错误码",
    )


def _assert_public_employee_data_owned(data: dict, subject: OracleSubject, *, label: str) -> None:
    bs._check(data.get("status") == "completed", f"{label}公共本人医疗期查询未完成")
    bs._check(
        data.get("result_type") == bs.EMPLOYEE_DATA_RESULT_TYPE,
        f"{label}未路由到员工数据服务",
    )
    bs._check(data.get("error_code") is None, f"{label}出现了非预期错误码")
    balance = subject.medical_period["balance"]
    expected = f"您的医疗期余额为{balance}天。"
    bs._check(
        str(data.get("answer") or "").strip() == expected,
        f"{label}公共回答与预期医疗期答案不一致",
    )


def _assert_direct_employee_owned(data: dict, subject: OracleSubject, *, label: str) -> None:
    bs._check(data.get("status") == "succeeded", f"{label}员工医疗期查询未成功")
    bs._check(data.get("query_type") == "medical_period", f"{label}未返回医疗期查询")
    bs._check(data.get("source") == "stub", f"{label}数据来源非 stub")
    bs._check(data.get("employee_ref") == subject.employee_ref, f"{label}employee_ref与期望不一致")
    bs._check(data.get("error_code") is None, f"{label}出现了非预期错误码")
    bs._check(
        data.get("data") == dict(subject.medical_period),
        f"{label}医疗期数据与期望不一致",
    )


# --------------------------------------------------------------------------
# 两个已映射主体：公共 Orchestrator 查询（真实模型路由 + 医疗期词面/数值）
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_mapped_subject_a_public_employee_data_returns_owned_balance(
    probes, subject_a
) -> None:
    message = bs.orchestrator_message(
        bs.IDENTITY_MESSAGE, execution_subject=_subject_payload(subject_a)
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_employee_data_owned(data, subject_a, label="主体A")


@MARK
@pytest.mark.asyncio
async def test_mapped_subject_b_public_employee_data_returns_owned_balance(
    probes, subject_b
) -> None:
    message = bs.orchestrator_message(
        bs.IDENTITY_MESSAGE, execution_subject=_subject_payload(subject_b)
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_employee_data_owned(data, subject_b, label="主体B")


# --------------------------------------------------------------------------
# Employee Data 结构化 medical_period（精确数据行 + 精确 ref + source + query_type）
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_direct_employee_data_subject_a_exact_medical_and_ref(probes, subject_a) -> None:
    internal = bs.derive_internal_user_id(subject_a.subject_kind, subject_a.subject_id)
    message = bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=internal)
    data = await bs.request_task(probes, "employee_data", message)
    _assert_direct_employee_owned(data, subject_a, label="主体A")


@MARK
@pytest.mark.asyncio
async def test_direct_employee_data_subject_b_exact_medical_and_ref(probes, subject_b) -> None:
    internal = bs.derive_internal_user_id(subject_b.subject_kind, subject_b.subject_id)
    message = bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=internal)
    data = await bs.request_task(probes, "employee_data", message)
    _assert_direct_employee_owned(data, subject_b, label="主体B")


# --------------------------------------------------------------------------
# 稳定性 / 并发 / 共享上下文隔离：每次结果都做完整精确断言
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_repeat_subject_is_stable(probes, subject_a) -> None:
    internal = bs.derive_internal_user_id(subject_a.subject_kind, subject_a.subject_id)
    first = await bs.request_task(
        probes, "employee_data", bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=internal)
    )
    second = await bs.request_task(
        probes, "employee_data", bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=internal)
    )
    _assert_direct_employee_owned(first, subject_a, label="首次")
    _assert_direct_employee_owned(second, subject_a, label="重复")


@MARK
@pytest.mark.asyncio
async def test_concurrent_two_subjects_distinct_refs(probes, subject_a, subject_b) -> None:
    ia = bs.derive_internal_user_id(subject_a.subject_kind, subject_a.subject_id)
    ib = bs.derive_internal_user_id(subject_b.subject_kind, subject_b.subject_id)
    message_a = bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=ia)
    message_b = bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=ib)
    data_a, data_b = await asyncio.gather(
        bs.request_task(probes, "employee_data", message_a),
        bs.request_task(probes, "employee_data", message_b),
    )
    _assert_direct_employee_owned(data_a, subject_a, label="并发主体A")
    _assert_direct_employee_owned(data_b, subject_b, label="并发主体B")
    bs._check(
        data_a.get("employee_ref") != data_b.get("employee_ref"),
        "并发两主体 employee_ref 未区分",
    )
    bs._check(
        data_a.get("data", {}).get("balance") != data_b.get("data", {}).get("balance"),
        "并发两主体 medical_period.balance 未区分",
    )


@MARK
@pytest.mark.asyncio
async def test_shared_context_does_not_cross_owner_identity(
    probes, subject_a, subject_b
) -> None:
    """同一 context 下先后提交两个主体：各自只拿到自己的身份，不交叉污染。"""
    shared = bs.new_context()
    ia = bs.derive_internal_user_id(subject_a.subject_kind, subject_a.subject_id)
    ib = bs.derive_internal_user_id(subject_b.subject_kind, subject_b.subject_id)
    message_a = bs.employee_message(bs.IDENTITY_MESSAGE, session_id=shared, internal_user_id=ia)
    message_b = bs.employee_message(bs.IDENTITY_MESSAGE, session_id=shared, internal_user_id=ib)
    data_a = await bs.request_task(probes, "employee_data", message_a)
    data_b = await bs.request_task(probes, "employee_data", message_b)
    _assert_direct_employee_owned(data_a, subject_a, label="共享上下文A")
    _assert_direct_employee_owned(data_b, subject_b, label="共享上下文B")
    bs._check(data_a.get("employee_ref") != data_b.get("employee_ref"), "共享上下文中两主体未隔离")


# --------------------------------------------------------------------------
# 匿名 / 未映射 / platform_service 同 id 一律 identity_unverified
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_anonymous_public_own_data_fails_identity_unverified(probes) -> None:
    data = await bs.request_task(probes, "orchestrator", bs.orchestrator_message(bs.IDENTITY_MESSAGE))
    _assert_identity_unverified(data, "匿名")


@MARK
@pytest.mark.asyncio
async def test_unmapped_subject_public_own_data_fails_identity_unverified(probes) -> None:
    message = bs.orchestrator_message(
        bs.IDENTITY_MESSAGE, execution_subject=_unmapped_subject()
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_identity_unverified(data, "未映射主体")


@MARK
@pytest.mark.asyncio
async def test_unmapped_subject_direct_employee_data_fails_identity_unverified(probes) -> None:
    unmapped = _unmapped_subject()
    internal = bs.derive_internal_user_id(unmapped["subject_kind"], unmapped["subject_id"])
    data = await bs.request_task(
        probes, "employee_data", bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=internal)
    )
    _assert_identity_unverified(data, "未映射主体(直接)")


@MARK
@pytest.mark.asyncio
async def test_platform_service_same_id_does_not_inherit_user_mapping(probes, subject_a) -> None:
    """与已映射 platform_user 相同 subject_id 的 platform_service 不得继承其映射。"""
    svc = {"subject_id": subject_a.subject_id, "subject_kind": bs.SERVICE_KIND}
    service_internal = bs.derive_internal_user_id(svc["subject_kind"], svc["subject_id"])
    user_internal = bs.derive_internal_user_id(subject_a.subject_kind, subject_a.subject_id)
    bs._check(
        service_internal != user_internal,
        "platform_service 与 platform_user 同 id 派生 internal_user_id 不应相同",
    )
    data = await bs.request_task(
        probes, "employee_data", bs.employee_message(bs.IDENTITY_MESSAGE, internal_user_id=service_internal)
    )
    _assert_identity_unverified(data, "platform_service 同 id")


# --------------------------------------------------------------------------
# 公共输入安全：未知 metadata 键（含 null/零值）与 execution_subject 内部敏感/非法值
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden,value",
    [
        ("employee_id", None),
        ("corp_id", 0),
        ("client_secret", None),
        ("caller_agent", ""),
    ],
)
async def test_public_unknown_metadata_keys_rejected(probes, forbidden, value) -> None:
    message = bs.orchestrator_message(bs.IDENTITY_MESSAGE, extra_metadata={forbidden: value})
    rejected = await bs.request_reject(probes, "orchestrator", message)
    bs._check(rejected, f"公共环境未知 metadata 键 {forbidden} 未被协议拒绝(-32602)")


@MARK
@pytest.mark.asyncio
async def test_public_execution_subject_forbidden_fields_rejected(probes) -> None:
    subject = {"subject_id": "snow-emp-x", "subject_kind": bs.USER_KIND, "employee_id": "EMP-1"}
    message = bs.orchestrator_message(bs.IDENTITY_MESSAGE, execution_subject=subject)
    data = await bs.request_task(probes, "orchestrator", message)
    bs._check(data.get("status") == "failed", "含 employee_id 的 execution_subject 未被拒绝为合同错误")
    bs._check(data.get("error_code") == "contract_error", "含 employee_id 的 execution_subject 未返回 contract_error")


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_subject",
    [
        {"subject_id": None, "subject_kind": bs.USER_KIND},
        {"subject_id": 0, "subject_kind": bs.USER_KIND},
        {"subject_id": "snow-x", "subject_kind": None},
    ],
)
async def test_public_execution_subject_null_zero_rejected(probes, bad_subject) -> None:
    message = bs.orchestrator_message(bs.IDENTITY_MESSAGE, execution_subject=bad_subject)
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_rejected_outcome(data, "null/零值主体")


# --------------------------------------------------------------------------
# 匿名 / 未映射 Leave 录入（核对权限）：不得因普通业务文本而回退成默认员工
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_anonymous_leave_rejected_identity_unverified(probes) -> None:
    data = await bs.request_task(probes, "orchestrator", bs.orchestrator_message(LEAVE_FULL))
    _assert_identity_unverified(data, "匿名请假")


@MARK
@pytest.mark.asyncio
async def test_unmapped_leave_rejected_identity_unverified(probes) -> None:
    message = bs.orchestrator_message(LEAVE_FULL, execution_subject=_unmapped_subject())
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_identity_unverified(data, "未映射主体请假")


@MARK
@pytest.mark.asyncio
async def test_cross_owner_same_task_continuation_isolation(probes, subject_a, subject_b) -> None:
    """同一 task/context 的续接不得改变所有者：B 不得接管 A，A 仍能恢复自己的录入。"""
    resp_a = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(LEAVE_INTRO, execution_subject=_subject_payload(subject_a)),
    )
    data_a = resp_a.data
    bs._check(data_a.get("status") == "input_required", "主体A未进入请假录入澄清")
    bs._check(data_a.get("error_code") == "input_required", "主体A请假录入未返回 input_required")
    task_id, context_id = resp_a.task.id, resp_a.task.context_id

    # B 也是有效员工，但不能续接 A 的 task/context。
    b_outcome = await bs.request_continuation(
        probes, "orchestrator",
        bs.orchestrator_message(LEAVE_FULL, execution_subject=_subject_payload(subject_b),
                                context_id=context_id, task_id=task_id),
    )
    if not b_outcome.rejected:
        bs._check(b_outcome.response is not None, "跨所有者续接未获得协议拒绝或结构化结果")
        data_b = b_outcome.response.data
        bs._check(data_b.get("status") in ("rejected", "failed"), "跨所有者续接被当作正常业务结果")
        bs._check(
            data_b.get("error_code") in ("contract_error", bs.ERROR_IDENTITY_UNVERIFIED),
            "跨所有者续接未返回精确 contract_error/identity_unverified",
        )
        bs._check(b_outcome.response.task.id == task_id, "跨所有者续接改变了任务 id")

    # A 仍可续接同一任务并得到自己的录入状态（未提交）。
    try:
        resp_a2 = await bs.request_full(
            probes, "orchestrator",
            bs.orchestrator_message("2026年9月10日", execution_subject=_subject_payload(subject_a),
                                    context_id=context_id, task_id=task_id),
        )
    except bs.AcceptanceError:
        bs._check(False, "跨所有者续接后主体A无法恢复原任务")
        return
    data_a2 = resp_a2.data
    bs._check(resp_a2.task.id == task_id, "主体A续接未保留原任务")
    bs._check(data_a2.get("status") == "input_required", "主体A续接后未得到自己的录入状态")
    bs._check(data_a2.get("error_code") == "input_required", "主体A续接后未返回 input_required")
    bs._check(all((m.metadata or {}).get("execution_subject") != _subject_payload(subject_b)
                 for m in (resp_a2.task.history or [])), "被拒绝的主体B消息污染了原任务历史")


# --------------------------------------------------------------------------
# 免同意只读：匿名政策咨询（consult，非本地兜底）/ 匿名问候（真实模型）
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_anonymous_public_policy_returns_consultation(probes) -> None:
    data = await bs.request_task(probes, "orchestrator", bs.orchestrator_message("公司的年假制度是什么"))
    bs._check(data.get("status") == "completed", "匿名政策咨询未完成")
    bs._check(data.get("result_type") == "consultation", "匿名政策咨询未返回咨询结果")
    bs._check(bool(str(data.get("answer") or "").strip()), "匿名政策咨询没有非空回答")
    bs._check(data.get("error_code") is None, "匿名政策咨询出现非预期错误码")


@MARK
@pytest.mark.asyncio
async def test_anonymous_greeting_runs_real_model(probes) -> None:
    data = await bs.request_task(probes, "orchestrator", bs.orchestrator_message("你好"))
    bs._check(data.get("status") == "completed", "匿名问候未完成")
    bs._check(bool(str(data.get("answer") or "").strip()), "匿名问候没有非空回答")
    bs._check(data.get("error_code") is None, "匿名问候出现非预期错误码")


# --------------------------------------------------------------------------
# 已映射主体请假录入：止步于澄清（缺日期），绝不提交事务
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_leave_intake_non_submitting_returns_clarification(probes, subject_a) -> None:
    message = bs.orchestrator_message(LEAVE_INTRO, execution_subject=_subject_payload(subject_a))
    data = await bs.request_task(probes, "orchestrator", message)
    bs._check(data.get("status") == "input_required", "请假录入未进入澄清（未提交事务）")
    bs._check(data.get("error_code") == "input_required", "请假录入未返回 input_required")
