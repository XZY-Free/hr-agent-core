"""WP-02「日单位 LeaveDraft 确认生命线」远端验收（TESTS ONLY）。

范围：只覆盖「已展示的日单位权威草稿 → 下一轮明确确认进入既有干跑边界 → 终态 + 原值提交表单」
的连续用户流；以及否定确认 / 历史摘要 / 同时修改都不得提交。只读真实 Orchestrator（A2A），
不 import apps/packages/veadk，无本地应用/模型/服务/ASGI/mock/skip/xfail，不调用 localhost。

冻结行为（来自已发布 stub 与 ROOT 已读生产代码，本文件不修复/不注入任何业务数据）：
- 年休假标准名「年休假」，HOLIDAY_TYPE_CODE["年休假"]="A31"（测试不能 import 业务包，从代码
  阅读填入固定公开 code）。
- 2026-10-12 ~ 2026-10-30 为 stub 明确返回 WORK 08:00–17:00 的日期；服务端年假余额 fake4，
  leaveUnit=day。确认后公共 completed，data.draft.status=terminal；data.submission.dry_run=true、
  submitted=false、form 为原 day 合同（typeName/typeCode/startDate/startTime/endDate/endTime/
  reasons/leaveDays），不含 employeeId/corp_id/secret；不另造最终 hour actionJSON。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体/oracle/原始响应正文；
不打印凭据/env/ref。HTTP 401/500/timeout 与未知协议错误一律视为失败，绝不当作预期业务拒绝。
不追求形式 RED；若线上已满足即无需生产修改，交由 root 运行后判断。

本文件为独立新文件，不修改其它 worker 的生产文件或已有测试。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 冻结基线：只读远端 -> 三段年假 ready 基线（不填写事由）。
BASE_MESSAGE = "我要请2026年10月12日起3天年假，不填写事由，请先核对并让我确认。"
CONFIRM_MESSAGE = "确认提交"

# 发布事实与代码阅读得到的合同值。
TYPE_STANDARD = "年休假"
# HOLIDAY_TYPE_CODE["年休假"]="A31"（packages/hr_domain/constants/leave_rules.py），测试不 import 业务包。
TYPE_CODE = "A31"
WORK_START = "08:00"
WORK_END = "17:00"
BASE_START = "2026-10-12"
BASE_END = "2026-10-14"
CHANGED_START = "2026-10-19"
CHANGED_END = "2026-10-21"

# 来源精确契约。
_DATE_SOURCE_ALLOWED = ("normalized_user", "schedule", "rule")   # 不允许 user/system
_TIME_SOURCE = "schedule"
_DURATION_VALUE_SOURCE = "rule"
_DURATION_UNIT_SOURCE = "rule"

_TERMINAL_OR_CONFIRMED = frozenset({"confirmed", "terminal"})
# 提交表单的公共字段集合（精确，不含 employeeId/corp_id/secret/apply_id）。
_FORM_KEYS = frozenset({
    "typeCode", "typeName", "startDate", "startTime",
    "endDate", "endTime", "reasons", "leaveDays",
})


# --------------------------------------------------------------------------
# fixtures（与已有 WP02 沿用完全相同）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    # 校验（唯一、双主体、ref 唯一、医疗余额互异）在装入期完成，失败即整体失败。
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


# --------------------------------------------------------------------------
# 复用断言（generic message；不打印主体 / oracle / draft 原始值；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_public_input_required(data: dict, *, label: str) -> None:
    bs._check(data.get("status") == "input_required",
              f"{label}公共顶层状态未映射为 input_required")
    bs._check(data.get("error_code") == "input_required",
              f"{label}公共顶层未返回 input_required 错误码")


def _answer_of(data: dict, *, label: str) -> str:
    answer = data.get("answer")
    bs._check(isinstance(answer, str) and answer, f"{label}公共结果缺少 answer")
    return answer


def _draft_id_of(draft: dict, *, label: str) -> str:
    draft_id = draft.get("draft_id")
    bs._check(isinstance(draft_id, str) and draft_id, f"{label}草稿 draft_id 为空")
    return draft_id


def _revision_of(draft: dict, *, label: str) -> int:
    # revision 必须是 int 且 > 0；type(...) is int 排除 bool（True 是 int 子类）。
    revision = draft.get("revision")
    bs._check(type(revision) is int and revision > 0,
              f"{label}revision 必须为大于 0 的整数(int)")
    return revision


def _assert_type_standard(draft: dict, *, label: str) -> None:
    bs._check(draft.get("normalized_type_name") == TYPE_STANDARD,
              f"{label}标准假名不是 年休假")


def _assert_draft_dates(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_date") == start,
              f"{label}权威起始日期与期望不一致")
    bs._check(draft.get("authoritative_end_date") == end,
              f"{label}权威结束日期与期望不一致")


def _assert_draft_time(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_time") == start,
              f"{label}权威开始时间与期望不一致")
    bs._check(draft.get("authoritative_end_time") == end,
              f"{label}权威结束时间与期望不一致")
    bs._check(draft.get("authoritative_start_time_source") == _TIME_SOURCE,
              f"{label}权威时段开始来源非 schedule")
    bs._check(draft.get("authoritative_end_time_source") == _TIME_SOURCE,
              f"{label}权威时段结束来源非 schedule")


def _assert_authoritative_duration(draft: dict, *, value, duration_unit: str, label: str) -> None:
    bs._check(draft.get("authoritative_duration_value") == value,
              f"{label}权威时长与期望不一致")
    bs._check(draft.get("authoritative_duration_unit") == duration_unit,
              f"{label}权威时长单位与期望不一致")


def _assert_date_sources(draft: dict, *, label: str) -> None:
    # 日期权威源精确契约：只允许 normalized_user/schedule/rule，不允许 user/system。
    start_src = draft.get("authoritative_start_date_source")
    end_src = draft.get("authoritative_end_date_source")
    bs._check(start_src in _DATE_SOURCE_ALLOWED, f"{label}权威起始日期来源非法")
    bs._check(end_src in _DATE_SOURCE_ALLOWED, f"{label}权威结束日期来源非法")


def _assert_duration_sources(draft: dict, *, label: str) -> None:
    bs._check(draft.get("authoritative_duration_value_source") == _DURATION_VALUE_SOURCE,
              f"{label}权威时长值来源非 rule")
    bs._check(draft.get("authoritative_duration_unit_source") == _DURATION_UNIT_SOURCE,
              f"{label}权威时长单位来源非 rule")


def _assert_answer_displayed(answer: str, *, label: str) -> None:
    """ready 态 answer 必须把权威草稿展示给用户（「已展示」是确认的合法前提）。"""
    bs._check(BASE_START in answer, f"{label}answer 未展示权威起始日期")
    bs._check(BASE_END in answer, f"{label}answer 未展示权威结束日期")
    bs._check(WORK_START in answer, f"{label}answer 未展示权威开始时间")
    bs._check(WORK_END in answer, f"{label}answer 未展示权威结束时间")
    bs._check("确认提交" in answer, f"{label}answer 未请求确认")


# --------------------------------------------------------------------------
# 前置 ready 基线：完整校验全部字段 + 来源，再从正确初态出发，避免假通过。
# --------------------------------------------------------------------------
def _require_ready_three_day(data: dict, *, label: str) -> tuple[str, int]:
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(draft.get("status") == "ready_for_confirmation",
              f"{label}基线未进入 ready_for_confirmation")
    bs._check(draft.get("status") not in _TERMINAL_OR_CONFIRMED,
              f"{label}基线不应为 confirmed/terminal")
    _assert_type_standard(draft, label=label)
    draft_id = _draft_id_of(draft, label=label)
    revision = _revision_of(draft, label=label)
    bs._check(draft.get("requested_start_date") == BASE_START,
              f"{label}requested_start_date 与期望不一致")
    _assert_draft_dates(draft, start=BASE_START, end=BASE_END, label=label)
    _assert_draft_time(draft, start=WORK_START, end=WORK_END, label=label)
    _assert_authoritative_duration(draft, value=3, duration_unit="day", label=label)
    _assert_date_sources(draft, label=label)
    _assert_duration_sources(draft, label=label)
    bs._check((draft.get("reason") or "") == "", f"{label}基线理由应为空")
    inner = bs.public_data(data, label=label)
    missing = inner.get("missing_fields")
    bs._check(isinstance(missing, list) and not missing,
              f"{label}ready 态不应存在缺失槽位")
    bs._check(inner.get("submission") is None,
              f"{label}ready 态不应携带提交结果")
    _assert_answer_displayed(_answer_of(data, label=label), label=label)
    return draft_id, revision


# --------------------------------------------------------------------------
# 确认后的终态 + 提交表单校验（原 day 合同，精确到字段集合与逐字段值）。
# --------------------------------------------------------------------------
def _assert_completed_terminal(data: dict, *, label: str) -> dict:
    bs._check(data.get("status") == "completed", f"{label}公共顶层状态应为 completed")
    draft = bs.public_draft(data, label=label)
    bs._check(draft.get("status") == "terminal",
              f"{label}草稿状态应为 terminal")
    bs._check(draft.get("status") in _TERMINAL_OR_CONFIRMED,
              f"{label}草稿应为终态")
    return draft


def _assert_form(form, *, label: str, type_name: str, type_code: str,
                 start: str, start_time: str, end: str, end_time: str,
                 reasons: str, leave_days) -> None:
    bs._check(isinstance(form, dict), f"{label}提交表单应为字典")
    bs._check(set(form) == _FORM_KEYS, f"{label}提交表单字段集合不符")
    bs._check(form.get("typeName") == type_name, f"{label}表单 typeName 不符")
    bs._check(form.get("typeCode") == type_code, f"{label}表单 typeCode 不符")
    bs._check(form.get("startDate") == start, f"{label}表单 startDate 不符")
    bs._check(form.get("startTime") == start_time, f"{label}表单 startTime 不符")
    bs._check(form.get("endDate") == end, f"{label}表单 endDate 不符")
    bs._check(form.get("endTime") == end_time, f"{label}表单 endTime 不符")
    bs._check(form.get("reasons") == reasons, f"{label}表单 reasons 不符")
    bs._check(form.get("leaveDays") == leave_days, f"{label}表单 leaveDays 不符")
    for key in ("employeeId", "corp_id", "corpId", "secret", "employee_id", "apply_id"):
        bs._check(key not in form, f"{label}提交表单不应包含敏感/内部字段 {key}")


def _assert_submission(data: dict, *, label: str,
                       start: str, end: str, reasons: str, leave_days) -> None:
    inner = bs.public_data(data, label=label)
    submission = inner.get("submission")
    bs._check(isinstance(submission, dict), f"{label}公共结果未返回 submission 对象")
    bs._check(submission.get("submitted") is False,
              f"{label}submission.submitted 应为 False")
    bs._check(submission.get("dry_run") is True,
              f"{label}submission.dry_run 应为 True")
    _assert_form(submission.get("form"), label=label,
                 type_name=TYPE_STANDARD, type_code=TYPE_CODE,
                 start=start, start_time=WORK_START, end=end, end_time=WORK_END,
                 reasons=reasons, leave_days=leave_days)


# --------------------------------------------------------------------------
# 否定/读态不变校验：同 draft_id、同 revision、权威不变、不得带入成功提交结果。
# --------------------------------------------------------------------------
def _assert_unchanged_ready(data: dict, base_draft_id: str, base_revision: int, *, label: str) -> None:
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(draft.get("status") == "ready_for_confirmation",
              f"{label}应保持 ready_for_confirmation")
    bs._check(draft.get("status") not in _TERMINAL_OR_CONFIRMED,
              f"{label}不应进入 confirmed/terminal")
    bs._check(draft.get("draft_id") == base_draft_id, f"{label}draft_id 被改动")
    bs._check(draft.get("revision") == base_revision, f"{label}revision 被改动")
    _assert_draft_dates(draft, start=BASE_START, end=BASE_END, label=label)
    _assert_authoritative_duration(draft, value=3, duration_unit="day", label=label)
    bs._check((draft.get("reason") or "") == "", f"{label}理由应保持为空")
    inner = bs.public_data(data, label=label)
    bs._check(inner.get("submission") is None,
              f"{label}不应携带成功提交结果")
    return draft


# --------------------------------------------------------------------------
# 流程步骤复用：开 ready 基线 / 下一轮确认提交。
# --------------------------------------------------------------------------
async def _open_ready(probes, subject: OracleSubject, *, label: str):
    payload = _subject_payload(subject)
    message = bs.orchestrator_message(BASE_MESSAGE, execution_subject=payload)
    resp = await bs.request_full(probes, "orchestrator", message)
    draft_id, revision = _require_ready_three_day(resp.data, label=label)
    return resp, draft_id, revision


async def _confirm(probes, subject: OracleSubject, *, task_id: str, context_id: str, label: str):
    payload = _subject_payload(subject)
    message = bs.orchestrator_message(
        CONFIRM_MESSAGE, context_id=context_id, task_id=task_id, execution_subject=payload,
    )
    return await bs.request_full(probes, "orchestrator", message)


# --------------------------------------------------------------------------
# 1) READY → 下一轮明确确认 → terminal + 原值 form（先精确校验前置 ready，再确认）
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_confirm_ready_next_round_terminal_original_form(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    resp, draft_id, revision = await _open_ready(probes, subject_a, label="前置ready")
    task_id = resp.task.id
    context_id = resp.task.context_id

    done = await _confirm(probes, subject_a, task_id=task_id, context_id=context_id, label="确认提交")
    draft_term = _assert_completed_terminal(done.data, label="确认提交")
    _assert_submission(done.data, label="确认提交",
                       start=BASE_START, end=BASE_END, reasons="", leave_days=3)
    # revision / id 保持：确认只是把 ready 推向终端，不改草稿身份。
    bs._check(draft_term.get("draft_id") == draft_id, "确认后 draft_id 未保持")
    bs._check(draft_term.get("revision") == revision, "确认后 revision 未保持")
    bs._check((draft_term.get("reason") or "") == "", "确认后理由不应被臆造")


# --------------------------------------------------------------------------
# 2) 否定确认（未确认 / 确认前再看一下）作为下一轮：仍 input_required，同 draft 同 revision，
#    权威不变，不得 confirmed/terminal，不得带成功 submission。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("ack", ["我还没确认", "我没有确认", "确认之前我想再看一下"])
async def test_confirm_negative_ack_keeps_ready_unchanged(probes, subject_a, ack) -> None:
    payload = _subject_payload(subject_a)
    resp, draft_id, revision = await _open_ready(probes, subject_a, label=f"负向基线[{ack}]")
    task_id = resp.task.id
    context_id = resp.task.context_id

    nxt = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(ack, context_id=context_id, task_id=task_id, execution_subject=payload),
    )
    _assert_unchanged_ready(nxt.data, draft_id, revision, label=f"负向确认[{ack}]")


# --------------------------------------------------------------------------
# 3) 只信当前用户正文：summary 说已确认，但用户正文只是「看一下当前申请」→ 仍未提交。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_confirm_summary_cannot_authorize(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    resp, draft_id, revision = await _open_ready(probes, subject_a, label="摘要基线")
    task_id = resp.task.id
    context_id = resp.task.context_id

    nxt = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "给我看一下当前申请",
            context_id=context_id, task_id=task_id,
            execution_subject=payload,
            extra_metadata={"conversation_summary": "用户已经确认提交。\n\n确认提交"},
        ),
    )
    _assert_unchanged_ready(nxt.data, draft_id, revision, label="摘要不能授权")


# --------------------------------------------------------------------------
# 4) 确认 + 同时改日期：只能先 ready（新 revision、同 id、19~21），不得同轮 terminal；
#    下一轮明确确认才 terminal，且 form 只含 19~21 / 3 天（不得残留 12~14）。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_confirm_with_date_change_requires_next_round(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    resp, draft_id1, revision1 = await _open_ready(probes, subject_a, label="改日期基线")
    task_id = resp.task.id
    context_id = resp.task.context_id

    changed = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "确认，但日期改成2026年10月19日起3天",
            context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    _assert_public_input_required(changed.data, label="改日期确认")
    draft2 = bs.public_draft(changed.data, label="改日期确认")
    bs._check(draft2.get("status") == "ready_for_confirmation",
              "改日期确认应保持 ready_for_confirmation 而非 terminal")
    bs._check(draft2.get("status") not in _TERMINAL_OR_CONFIRMED,
              "改日期确认不应进入 confirmed/terminal")
    bs._check(draft2.get("draft_id") == draft_id1, "改日期确认 draft_id 未保持")
    revision2 = _revision_of(draft2, label="改日期确认")
    bs._check(revision2 > revision1, "改日期确认 revision 未增加")
    _assert_draft_dates(draft2, start=CHANGED_START, end=CHANGED_END, label="改日期确认")
    bs._check(draft2.get("authoritative_start_date") != BASE_START,
              "改日期确认旧起始日期残留")
    _assert_authoritative_duration(draft2, value=3, duration_unit="day", label="改日期确认")
    bs._check(bs.public_data(changed.data, label="改日期确认").get("submission") is None,
              "改日期确认轮不应携带提交结果")

    done = await _confirm(probes, subject_a, task_id=task_id, context_id=context_id, label="改日期后确认")
    draft_term = _assert_completed_terminal(done.data, label="改日期后确认")
    _assert_submission(done.data, label="改日期后确认",
                       start=CHANGED_START, end=CHANGED_END, reasons="", leave_days=3)
    bs._check(draft_term.get("draft_id") == draft_id1, "改日期后确认 draft_id 未保持")
    bs._check(draft_term.get("revision") == revision2, "改日期后确认 revision 未保持")


# --------------------------------------------------------------------------
# 5) 同一 task 终态后再发「确认提交」→ 协议 -32602 拒绝（bs.request_reject 只认该错误，
#    401/500/timeout 不等于通过；绝不用 catch-any 成功）。先验证首次 terminal/form 再重复。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_reconfirm_after_terminal_rejects_protocol(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    resp, draft_id, revision = await _open_ready(probes, subject_a, label="重提基线")
    task_id = resp.task.id
    context_id = resp.task.context_id

    first = await _confirm(probes, subject_a, task_id=task_id, context_id=context_id, label="首确认")
    draft_term = _assert_completed_terminal(first.data, label="首确认")
    _assert_submission(first.data, label="首确认",
                       start=BASE_START, end=BASE_END, reasons="", leave_days=3)
    bs._check(draft_term.get("draft_id") == draft_id, "重提-首确认 draft_id 未保持")
    bs._check(draft_term.get("revision") == revision, "重提-首确认 revision 未保持")

    rejected = await bs.request_reject(
        probes, "orchestrator",
        bs.orchestrator_message(
            CONFIRM_MESSAGE, context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    bs._check(rejected, "同任务终态后再次确认提交应以 -32602 协议拒绝")


# --------------------------------------------------------------------------
# 6) 明确理由贯穿到 final：先改 reason（新 revision、reason_source=user、权威不变），
#    再确认，form.reasons=该原文。同流程，不做其它 WP。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_confirmation_carries_reason_to_final_form(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    resp, draft_id, revision1 = await _open_ready(probes, subject_a, label="理由基线")
    task_id = resp.task.id
    context_id = resp.task.context_id

    with_reason = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "理由改成去医院复诊",
            context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    _assert_public_input_required(with_reason.data, label="改理由")
    draft2 = bs.public_draft(with_reason.data, label="改理由")
    bs._check(draft2.get("status") == "ready_for_confirmation", "改理由后应等待重新确认")
    bs._check(draft2.get("status") not in _TERMINAL_OR_CONFIRMED,
              "改理由后不应进入 confirmed/terminal")
    bs._check(draft2.get("draft_id") == draft_id, "改理由后 draft_id 未保持")
    revision2 = _revision_of(draft2, label="改理由")
    bs._check(revision2 > revision1, "改理由后 revision 未增加")
    _assert_draft_dates(draft2, start=BASE_START, end=BASE_END, label="改理由")
    _assert_authoritative_duration(draft2, value=3, duration_unit="day", label="改理由")
    bs._check(draft2.get("reason") == "去医院复诊", "改理由后 reason 未逐字保留")
    bs._check(draft2.get("reason_source") == "user", "改理由后 reason_source 非 user")
    bs._check(bs.public_data(with_reason.data, label="改理由").get("submission") is None,
              "改理由轮不应携带提交结果")

    done = await _confirm(probes, subject_a, task_id=task_id, context_id=context_id, label="带理由确认")
    draft_term = _assert_completed_terminal(done.data, label="带理由确认")
    _assert_submission(done.data, label="带理由确认",
                       start=BASE_START, end=BASE_END, reasons="去医院复诊", leave_days=3)
    bs._check(draft_term.get("draft_id") == draft_id, "带理由确认 draft_id 未保持")
    bs._check(draft_term.get("revision") == revision2, "带理由确认 revision 未保持")
