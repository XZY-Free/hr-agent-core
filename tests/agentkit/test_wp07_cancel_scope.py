"""WP-07 Cancel 范围远端验收：一个不变量。

不变量：整改包不得暴露公共 tasks/cancel 能力。一个 input-required 的公共任务必须拒绝
cancel，且拒绝信号必须是 A2A UnsupportedOperationError 标准码 -32004；成功取消、
-32002(TaskNotCancelable)、-32602、网络/鉴权/其它 RPC 错误一律视为失败。同任务 resume
保持原样——本 RED 聚焦只覆盖 cancel，不触碰 resume（WP02/WP05 云续接已覆盖并纳入全量）。

范围：真实 HTTPS A2A 调用（AgentKit 开发 Orchestrator 公共端点）。全部经
business_support.request_full / request_cancel / orchestrator_message / load_identity_oracle。
主体取 oracle 第一主体；无本地应用/模型/服务、无 fake-model、无 ASGI、无 localhost 服务、
无 mock、不 skip/xfail、不打印主体/oracle/响应正文/answer/凭据/task id/异常消息。

当前验收部署：Orchestrator v29。本文件只在头注记录取证版本，不做版本硬断言；结论由
云端执行裁决。首轮只做公共可观察的结构化字段 status / result_type / route_target / data.draft
断言；协议/网络失败必须让测试直接失败（request_full/request_cancel 收敛为 AcceptanceError /
CancelOutcome.category），绝不当作预期业务拒绝。

安全：所有布尔断言走 business_support._check()，避免 pytest 断言内省打印主体/oracle/
响应正文/answer/凭据/task id；不 import apps / packages / veadk；不写云端、不部署、不 commit。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# Leave 草稿 input_required 的可行领域状态（不由自然语言决定）。
_DRAFT_INPUT_REQUIRED_STATUSES = frozenset({"collecting", "ready_for_confirmation", "validation_failed"})


# --------------------------------------------------------------------------
# fixtures（与 WP-01..06 一致：subject A 为 oracle 第一条主体）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    # 校验（两条主体、ref 唯一、医疗余额互异）在装入期完成，失败即整体失败。
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


# --------------------------------------------------------------------------
# 复用断言（均不打印主体/oracle/draft 原始值/answer/凭据；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_no_sensitive(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id / secret / token 字段或子串。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            bs._check(key not in ("employee_id", "secret", "token"), f"{label}泄露敏感字段")
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, str):
        for token in ("employee_id", "secret", "token"):
            bs._check(token not in obj, f"{label}响应含敏感子串")


def _assert_input_required_leave(res: dict, *, label: str) -> None:
    """Leave：input_required + data.route_target=local + data.draft 为 dict 且 status 属收集/确认/校验失败。"""
    bs._check(res.get("status") == "input_required", f"{label}未映射为 input_required")
    bs._check(res.get("result_type") == "missing_information", f"{label}result_type非 missing_information")
    inner = res.get("data")
    bs._check(isinstance(inner, dict), f"{label}data负载非 dict")
    bs._check(inner.get("route_target") == "local", f"{label}route_target非 local")
    draft = inner.get("draft")
    bs._check(isinstance(draft, dict), f"{label}data.draft非 dict")
    bs._check(
        draft.get("status") in _DRAFT_INPUT_REQUIRED_STATUSES,
        f"{label}draft.status非收集/确认/校验失败",
    )
    bs._check(isinstance(res.get("answer"), str) and res.get("answer").strip(), f"{label}answer为空")
    _assert_no_sensitive(res, label=label)


# --------------------------------------------------------------------------
# 唯一不变量测试：首轮「我想请假」必须真实 input_required（真实 task/context id），
# 再用官方 client.cancel_task 请求取消，必须被 A2A -32004 UnsupportedOperation 拒绝。
# 任何成功取消/非 -32004/网络/鉴权错误都失败（request_cancel 收敛 unsupported=False）。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_input_required_public_task_rejects_cancel(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    first = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("我想请假", execution_subject=payload),
    )
    _assert_input_required_leave(first.data, label="Cancel首轮")

    task_id = first.task.id
    context_id = first.task.context_id
    bs._check(isinstance(task_id, str) and task_id, "Cancel首轮 task id 为空")
    bs._check(isinstance(context_id, str) and context_id, "Cancel首轮 context id 为空")

    outcome = await bs.request_cancel(probes, "orchestrator", task_id)
    bs._check(
        outcome.unsupported,
        "input-required 任务未按 A2A -32004 UnsupportedOperation 拒绝 cancel",
    )
