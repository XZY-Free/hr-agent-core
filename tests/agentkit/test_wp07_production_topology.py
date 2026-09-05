"""WP-07 生产拓扑云端验收：一个不变量。

不变量：WP-07 最终云端门禁绑定到「独立复核的每个 AgentKit 服务不可变镜像」，并通过已部署的
Orchestrator 证明全部三条公共生产分支：

1. 本地 Leave：映射主体两轮（ready → 同 task/context 明确确认）→ completed/terminal，
   公共 data.route_target=local 两轮，且确认只做干跑（submission.dry_run=true /
   submitted=false / form.leaveDays=3），无真实提交，无敏感字段/子串。
2. A2A Employee Data：映射主体「我的医疗期余额」→ completed / result_type=employee_data /
   data.route_target=employee_data，answer 逐字等于 oracle 提供的医疗期余额，无 draft、
   无敏感字段/子串。
3. A2A Consult：匿名「公司的年假制度是什么」→ completed / result_type=consultation /
   data.route_target=consult，answer 非空、error_code=None、无 draft、无敏感字段/子串。

范围：真实 HTTPS A2A 调用（AgentKit 已部署 Orchestrator 公共端点）。全部经
business_support.request_full / orchestrator_message / load_identity_oracle / public_data。
主体取 oracle 第一主体（subject_a）；匿名用例不携带 execution_subject。无本地应用/模型/服务、
无 fake-model、无 ASGI、无 localhost、无 mock、不 skip/xfail、不 import apps/packages/veadk、
不 inspect 本地实现、不做 test-only 路由，也不重复 WP01-06 已覆盖的用例。

安全：所有布尔断言走 business_support._check()，避免 pytest 断言内省打印主体/oracle/响应正文/
answer/凭据；递归安全校验拒绝 employee_id/secret/token 字段或子串且不打印响应；不打印
task id / answer / 主体 / oracle 数值。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 冻结基线：与已展示 ready 的公开稳定流一致（WP-02 已覆盖的 ready→确认由本文件作为
# 生产拓扑证据重新走一遍，强调 route_target 与干跑交易结果）。
_LEAVE_READY_MESSAGE = "我要请2026年10月12日起3天年假，不填写事由，请先核对并让我确认。"
_LEAVE_CONFIRM_MESSAGE = "确认提交"
_LEAVE_TYPE_STANDARD = "年休假"

# 冻结提交表单字段集合（精确；不含 employeeId/corp_id/corpId/secret/apply_id）。
_FORM_KEYS = frozenset({
    "typeCode", "typeName", "startDate", "startTime",
    "endDate", "endTime", "reasons", "leaveDays",
})


# --------------------------------------------------------------------------
# fixtures（与既有 WP01..06 一致：subject A 为 oracle 第一条主体）
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
# 复用断言（均不打印主体 / oracle / draft 原始值 / answer / 凭据；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_no_sensitive(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id/secret/token 字段或子串，绝不打印响应。"""
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


def _assert_route_target(data: dict, expected: str, *, label: str) -> dict:
    """公共主路由证据：data 必须是 dict 且 data.route_target 等于固定三值契约之一。

    route_target 由 Orchestrator 按实际选中 RouteTarget 生成，是本测试的主路由证据，
    与下游是否 completed 解耦；缺失即断言失败。
    """
    inner = bs.public_data(data, label=label)
    bs._check(inner.get("route_target") == expected, f"{label}route_target非 {expected}")
    return inner


# --------------------------------------------------------------------------
# 1) 本地 Leave：映射主体两轮（ready → 同 task/context 确认）→ terminal 干跑结果
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_public_leave_two_turn_confirm_terminal_local(probes, subject_a) -> None:
    """本地 Leave 公共分支：ready 后同 task/context 明确确认 → completed/terminal 干跑。

    route_target=local 两轮；确认只做干跑（dry_run=true / submitted=false /
    form.leaveDays=3），证明「已部署拓扑经公共 Orchestrator 可完成本地请假确认」而非真实提交。
    """
    payload = _subject_payload(subject_a)
    first = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(_LEAVE_READY_MESSAGE, execution_subject=payload),
    )
    data1 = first.data
    bs._check(data1.get("status") == "input_required",
              "Leave第一轮未映射为 input_required")
    bs._check(data1.get("result_type") == "missing_information",
              "Leave第一轮result_type非 missing_information")
    inner1 = _assert_route_target(data1, "local", label="Leave第一轮")
    draft1 = inner1.get("draft")
    bs._check(isinstance(draft1, dict), "Leave第一轮data.draft非 dict")
    bs._check(draft1.get("status") == "ready_for_confirmation",
              "Leave第一轮草稿未进入 ready_for_confirmation")
    bs._check(draft1.get("normalized_type_name") == _LEAVE_TYPE_STANDARD,
              "Leave第一轮假种非 年休假")
    bs._check(draft1.get("authoritative_duration_value") == 3,
              "Leave第一轮权威时长非 3 天")
    bs._check(draft1.get("authoritative_duration_unit") == "day",
              "Leave第一轮权威时长单位非 day")

    task_id = first.task.id
    context_id = first.task.context_id
    bs._check(isinstance(task_id, str) and task_id, "Leave第一轮 task id 为空")
    bs._check(isinstance(context_id, str) and context_id, "Leave第一轮 context id 为空")

    second = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            _LEAVE_CONFIRM_MESSAGE,
            context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    data2 = second.data
    bs._check(second.task.id == task_id, "Leave第二轮未保持原 task id")
    bs._check(second.task.context_id == context_id, "Leave第二轮未保持原 context id")
    bs._check(data2.get("status") == "completed", "Leave第二轮公共状态非 completed")
    inner2 = _assert_route_target(data2, "local", label="Leave第二轮")
    draft2 = inner2.get("draft")
    bs._check(isinstance(draft2, dict), "Leave第二轮data.draft非 dict")
    bs._check(draft2.get("status") == "terminal", "Leave第二轮草稿状态非 terminal")

    submission = inner2.get("submission")
    bs._check(isinstance(submission, dict), "Leave第二轮未返回 submission 对象")
    bs._check(submission.get("submitted") is False,
              "Leave第二轮 submission.submitted 应为 False")
    bs._check(submission.get("dry_run") is True,
              "Leave第二轮 submission.dry_run 应为 True")
    form = submission.get("form")
    bs._check(isinstance(form, dict), "Leave第二轮 submission.form 非 dict")
    bs._check(set(form) == _FORM_KEYS, "Leave第二轮提交表单字段集合不符")
    bs._check(form.get("typeName") == _LEAVE_TYPE_STANDARD,
              "Leave第二轮表单 typeName 不符")
    bs._check(form.get("leaveDays") == 3, "Leave第二轮表单 leaveDays 非 3")
    for key in ("employeeId", "corp_id", "corpId", "secret", "employee_id", "apply_id"):
        bs._check(key not in form, f"Leave第二轮提交表单不应包含敏感/内部字段 {key}")

    _assert_no_sensitive(data1, label="Leave第一轮")
    _assert_no_sensitive(data2, label="Leave第二轮")


# --------------------------------------------------------------------------
# 2) A2A Employee Data：映射主体「我的医疗期余额」→ 完成 + 逐字医疗期 answer
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_public_employee_medical_period_exact(probes, subject_a) -> None:
    """A2A Employee Data 公共分支：映射主体「我的医疗期余额」→ completed/employee_data。

    通过已部署 Orchestrator 走 employee_data，answer 必须逐字等于 oracle 提供的医疗期余额；
    结构化 result_type=employee_data 且 data.route_target=employee_data；无 draft、无敏感。
    """
    payload = _subject_payload(subject_a)
    resp = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("我的医疗期余额", execution_subject=payload),
    )
    data = resp.data
    bs._check(data.get("status") == "completed", "员工数据公共状态非 completed")
    bs._check(data.get("result_type") == "employee_data",
              "员工数据result_type非 employee_data")
    bs._check(data.get("error_code") is None, "员工数据出现非预期 error_code")
    inner = _assert_route_target(data, "employee_data", label="员工数据")
    bs._check("draft" not in inner, "员工数据不应输出草稿快照")

    expected_balance = subject_a.medical_period["balance"]
    expected_answer = f"您的医疗期余额为{expected_balance}天。"
    bs._check(data.get("answer") == expected_answer,
              "员工数据answer与oracle医疗期余额不一致")
    _assert_no_sensitive(data, label="员工数据")


# --------------------------------------------------------------------------
# 3) A2A Consult：匿名「公司的年假制度是什么」→ 完成 + consultation
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_public_anonymous_consult_policy(probes) -> None:
    """A2A Consult 公共分支：匿名「公司的年假制度是什么」→ completed/consultation。

    匿名不携带 execution_subject；通过已部署 Orchestrator 走 consult，result_type=consultation、
    data.route_target=consult；answer 非空且 error_code=None（稳定 Knowledge 结果），无 draft、
    无敏感字段/子串。
    """
    resp = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("公司的年假制度是什么"),
    )
    data = resp.data
    bs._check(data.get("status") == "completed", "政策咨询公共状态非 completed")
    bs._check(data.get("result_type") == "consultation",
              "政策咨询result_type非 consultation")
    bs._check(data.get("error_code") is None, "政策咨询出现非预期 error_code")
    inner = _assert_route_target(data, "consult", label="政策咨询")
    bs._check("draft" not in inner, "政策咨询不应输出草稿快照")
    bs._check(isinstance(data.get("answer"), str) and data.get("answer").strip(),
              "政策咨询answer为空")
    _assert_no_sensitive(data, label="政策咨询")
