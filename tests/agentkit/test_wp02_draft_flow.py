"""WP-02（生产草稿与确认前状态接线切片）远端验收。

范围：同一已映射员工在公共 Orchestrator 上，把「三天年假请求」推进到「经过校验的
显式 LeaveDraft 确认态」，然后修改日期 / 理由并以新 revision 重新确认；不足余额与
0 天不得变成可确认。只覆盖「生产草稿与确认前状态」接线，不做小时 / 夜班 / 扩窗 /
附件 / 路由 / 考勤 / 最终提交动作 JSON 等后续切片。

证据全部来自真实 HTTPS A2A 调用（三个 AgentKit 开发 Runtime 中的 orchestrator）。
无本地应用 / 模型 / 服务 / fake-model / ASGI；不 import apps/packages/veadk；
不读写 .env / 云配置 / 业务正文。公共 result.data.draft 是服务端显式 Draft 快照，
不是从 answer 解析，也不由自然语言决定状态。

草稿快照契约：统一使用现有领域 schema 字段（不做别名/容器兼容）：
normalized_type_name、requested_start_date、authoritative_start_date、
authoritative_end_date、authoritative_start_time、authoritative_end_time、
duration_value（用户请求层。保留）、authoritative_duration_value、
authoritative_duration_unit、reason 及各自 _source。

来源契约（精确）：日期权威源只允许 normalized_user/schedule/rule；时段源必须
schedule（本切片白班，两个端点都验证）；权威 duration_value_source 与
authoritative_duration_unit_source 必须 rule。

发布事实（来自已发布 stub，本测试不修正/注入业务数据）：年休假标准名「年休假」，
2026-10-12 ~ 2026-10-30 为 stub 明确返回 WORK 08:00–17:00 的日期。当前发布 Gaia
年休假余额为 4，但该余额行缺少 leaveUnit（单位未发布）。「day」是操作方 root 将在
对应实现发布时显式补充的测试数据，本测试不假设 day 已经发布；若缺少实际配置（如
未补 leaveUnit、余额/排班与事实不符），本测试应失败，绝不 skip / xfail。

安全：敏感断言全部走 business_support._check()，避免 pytest 断言内省打印主体 /
oracle / 原始响应正文；不打印凭据 / env / ref。HTTP 401/500/timeout 与未知协议
错误一律视为失败，绝不当作预期业务拒绝。

约定（本切片可观察状态）：
- 公共顶层 status/error_code 冻结；collecting / ready_for_confirmation /
  validation_failed 在需要用户提供或确认时均映射 input_required / error_code=input_required。
- 公共 result.data.missing_fields 用英文键：type_name/date/time_or_duration/reason。
- 校验失败 result.data.validation_error.code 为领域错误码。
"""

from __future__ import annotations

import asyncio
import re

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 发布事实：年休假标准名。
TYPE_STANDARD = "年休假"
# 2026-10-12 ~ 2026-10-30 为 stub 明确返回 WORK 08:00–17:00 的日期。
WORK_START = "08:00"
WORK_END = "17:00"

# 来源精确契约。
_DATE_SOURCE_ALLOWED = ("normalized_user", "schedule", "rule")   # 不允许 user/system
_TIME_SOURCE = "schedule"                                        # 白班两个端点
_DURATION_VALUE_SOURCE = "rule"
_DURATION_UNIT_SOURCE = "rule"

_TERMINAL_OR_CONFIRMED = frozenset({"confirmed", "terminal"})


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


def _status_of(draft: dict, *, label: str) -> str:
    status = draft.get("status")
    bs._check(isinstance(status, str) and status, f"{label}草稿缺失 status")
    return status


def _draft_id_of(draft: dict, *, label: str) -> str:
    draft_id = draft.get("draft_id")
    bs._check(isinstance(draft_id, str) and draft_id, f"{label}草稿 draft_id 为空")
    return draft_id


def _revision_of(draft: dict, *, label: str) -> int:
    """revision 必须是 int 且 > 0；type(...) is int 排除 bool（True 是 int 子类）。"""
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
    """日期权威源精确契约：只允许 normalized_user/schedule/rule，不允许 user/system。"""
    start_src = draft.get("authoritative_start_date_source")
    end_src = draft.get("authoritative_end_date_source")
    bs._check(start_src in _DATE_SOURCE_ALLOWED, f"{label}权威起始日期来源非法")
    bs._check(end_src in _DATE_SOURCE_ALLOWED, f"{label}权威结束日期来源非法")


def _assert_duration_sources(draft: dict, *, label: str) -> None:
    bs._check(draft.get("authoritative_duration_value_source") == _DURATION_VALUE_SOURCE,
              f"{label}权威时长值来源非 rule")
    bs._check(draft.get("authoritative_duration_unit_source") == _DURATION_UNIT_SOURCE,
              f"{label}权威时长单位来源非 rule")


def _missing_fields(data: dict, *, label: str) -> list:
    inner = bs.public_data(data, label=label)
    missing = inner.get("missing_fields")
    bs._check(isinstance(missing, list), f"{label}公共结果未返回 missing_fields 数组")
    return missing


def _assert_missing_empty(data: dict, *, label: str) -> None:
    missing = _missing_fields(data, label=label)
    bs._check(not missing, f"{label}ready 态不应存在缺失槽位")


def _validation_error_code(data: dict, *, label: str) -> str:
    inner = bs.public_data(data, label=label)
    validation = inner.get("validation_error")
    bs._check(isinstance(validation, dict), f"{label}公共结果未返回 validation_error 对象")
    code = validation.get("code")
    bs._check(isinstance(code, str) and code, f"{label}公共结果未返回 validation_error.code")
    return code


def _assert_not_confirmable_or_terminal(draft: dict, *, label: str) -> None:
    status = _status_of(draft, label=label)
    bs._check(status == "validation_failed", f"{label}草稿状态不是 validation_failed")
    bs._check(status not in _TERMINAL_OR_CONFIRMED,
              f"{label}不应进入 confirmed/terminal")


def _answer_of(data: dict, *, label: str) -> str:
    """公共顶层 answer：服务端渲染的确认摘要（不是从自然语言反推）。"""
    answer = data.get("answer")
    bs._check(isinstance(answer, str) and answer, f"{label}公共结果缺少 answer")
    return answer


def _assert_answer_day_duration(answer: str, value, *, label: str) -> None:
    """answer 中的天数投影：只接受 3/3.0 天（可带空格），不得把 13 天误收为 3 天。"""
    if value is None:
        return
    pattern = r"(?<![0-9.])%s(?:\.0)?\s*天" % int(value)
    bs._check(re.search(pattern, answer) is not None,
              f"{label}answer 未展示权威 {value} 天")


def _assert_answer_matches_draft(answer: str, draft: dict, *, label: str) -> None:
    """确认摘要必须投影已校验的权威草稿：日期/时段/时长逐字段一致。

    只做包含式投影检查，不假设标点/加粗/markdown；先经 _assert_draft_* 校验后再调用，
    保证先从服务端权威草稿（而非 answer 解析）拿到期望值。
    """
    bs._check(draft.get("authoritative_start_date") in answer,
              f"{label}answer 未展示权威起始日期")
    bs._check(draft.get("authoritative_end_date") in answer,
              f"{label}answer 未展示权威结束日期")
    bs._check(draft.get("authoritative_start_time") in answer,
              f"{label}answer 未展示权威开始时间")
    bs._check(draft.get("authoritative_end_time") in answer,
              f"{label}answer 未展示权威结束时间")
    _assert_answer_day_duration(answer, draft.get("authoritative_duration_value"),
                                label=label)


def _assert_answer_not_confirmation(answer: str, *, label: str) -> None:
    """validation_failed 的 answer 必须显示业务失败，而不是请求确认。"""
    bs._check("确认提交" not in answer and "请核对您的" not in answer,
              f"{label}validation_failed 的 answer 不应请求确认")


def _assert_answer_business_failure(answer: str, data: dict, *, label: str) -> None:
    """校验失败：answer 必须展示对应业务失败（validation_error.message），而非请求确认。"""
    _assert_answer_not_confirmation(answer, label=label)
    inner = bs.public_data(data, label=label)
    validation = inner.get("validation_error")
    bs._check(isinstance(validation, dict), f"{label}未返回 validation_error 对象")
    message = validation.get("message")
    bs._check(isinstance(message, str) and message, f"{label}validation_error.message 为空")
    bs._check(message in answer, f"{label}answer 未展示对应业务失败")


def _require_ready_three_day(data: dict, *, label: str) -> tuple[str, int]:
    """完整校验「三天年假 ready」基线，返回 (draft_id, revision)。

    初态不正确就失败，避免从错误初态跳到正确初态的假通过。基线假种/日期/时段/时长
    （含来源）与 missing 都精确校验。
    """
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(_status_of(draft, label=label) == "ready_for_confirmation",
              f"{label}基线未进入 ready_for_confirmation")
    _assert_type_standard(draft, label=label)
    draft_id = _draft_id_of(draft, label=label)
    revision = _revision_of(draft, label=label)
    bs._check(draft.get("requested_start_date") == "2026-10-12",
              f"{label}基线 requested_start_date 与期望不一致")
    _assert_draft_dates(draft, start="2026-10-12", end="2026-10-14", label=label)
    _assert_draft_time(draft, start=WORK_START, end=WORK_END, label=label)
    _assert_authoritative_duration(draft, value=3, duration_unit="day", label=label)
    _assert_date_sources(draft, label=label)
    _assert_duration_sources(draft, label=label)
    bs._check((draft.get("reason") or "") == "", f"{label}基线理由应为空")
    _assert_missing_empty(data, label=label)
    # 草稿基线精确校验后，立即校验它投影到 answer 的确认摘要逐字段一致。
    _assert_answer_matches_draft(_answer_of(data, label=label), draft, label=label)
    return draft_id, revision


# --------------------------------------------------------------------------
# 1) 三天年假请求 → 经校验的显式 Draft 确认态（不指定事由）
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_three_day_annual_ready_for_confirmation(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日起3天年假，不填写事由，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _require_ready_three_day(data, label="三天年假")


# --------------------------------------------------------------------------
# 2) 明确日期范围 12 至 14 日全天 → 同样权威 3 天，用户未给 leave_days
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_explicit_range_12_to_14_full_day(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日到10月14日全天年假，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="明确范围")
    draft = bs.public_draft(data, label="明确范围")

    bs._check(_status_of(draft, label="明确范围") == "ready_for_confirmation",
              "明确范围草稿未进入 ready_for_confirmation")
    _assert_type_standard(draft, label="明确范围")
    _draft_id_of(draft, label="明确范围")
    _revision_of(draft, label="明确范围")
    _assert_draft_dates(draft, start="2026-10-12", end="2026-10-14", label="明确范围")
    _assert_draft_time(draft, start=WORK_START, end=WORK_END, label="明确范围")
    _assert_authoritative_duration(draft, value=3, duration_unit="day", label="明确范围")
    _assert_date_sources(draft, label="明确范围")
    _assert_duration_sources(draft, label="明确范围")
    _assert_missing_empty(data, label="明确范围")
    _assert_answer_matches_draft(_answer_of(data, label="明确范围"), draft, label="明确范围")


# --------------------------------------------------------------------------
# 3) 缺槽位 collecting → 同 task/context 续接补全 → ready；draft_id 保持、revision 增加
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_missing_fields_collecting_then_ready(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    first = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("我想请年假", execution_subject=payload),
    )
    _assert_public_input_required(first.data, label="缺槽位第一轮")
    draft1 = bs.public_draft(first.data, label="缺槽位第一轮")
    bs._check(_status_of(draft1, label="缺槽位第一轮") == "collecting",
              "缺槽位第一轮草稿状态不是 collecting")
    _assert_type_standard(draft1, label="缺槽位第一轮")
    draft_id1 = _draft_id_of(draft1, label="缺槽位第一轮")
    revision1 = _revision_of(draft1, label="缺槽位第一轮")

    missing1 = _missing_fields(first.data, label="缺槽位第一轮")
    bs._check("date" in missing1 and "time_or_duration" in missing1,
              "缺槽位第一轮 missing 应含 date 与 time_or_duration")
    bs._check("reason" not in missing1, "缺槽位第一轮 missing 不应含 reason")

    task_id = first.task.id
    context_id = first.task.context_id
    second = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "2026年10月12日开始请3天，事由留空",
            context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    _assert_public_input_required(second.data, label="缺槽位第二轮")
    draft2 = bs.public_draft(second.data, label="缺槽位第二轮")
    bs._check(_status_of(draft2, label="缺槽位第二轮") == "ready_for_confirmation",
              "缺槽位第二轮草稿未进入 ready_for_confirmation")
    bs._check(_draft_id_of(draft2, label="缺槽位第二轮") == draft_id1,
              "缺槽位续接后 draft_id 未保持")
    revision2 = _revision_of(draft2, label="缺槽位第二轮")
    bs._check(revision2 > revision1, "缺槽位续接后 revision 未增加")
    _assert_draft_dates(draft2, start="2026-10-12", end="2026-10-14", label="缺槽位第二轮")
    _assert_authoritative_duration(draft2, value=3, duration_unit="day", label="缺槽位第二轮")
    _assert_missing_empty(second.data, label="缺槽位第二轮")


# --------------------------------------------------------------------------
# 4) 从 ready 修改日期 → 同 draft_id、新 revision；重新 ready_for_confirmation，
#    旧日期不可残留
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_modify_date_new_revision_ready(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    base = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("请2026年10月12日起3天年假", execution_subject=payload),
    )
    draft_id1, revision1 = _require_ready_three_day(base.data, label="改日期基线")

    task_id = base.task.id
    context_id = base.task.context_id
    changed = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "改到2026年10月19日开始，还是3天年假",
            context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    _assert_public_input_required(changed.data, label="改日期")
    draft2 = bs.public_draft(changed.data, label="改日期")

    bs._check(_status_of(draft2, label="改日期") == "ready_for_confirmation",
              "改日期后应重新 ready_for_confirmation 而非 completed")
    bs._check(_draft_id_of(draft2, label="改日期") == draft_id1,
              "改日期后 draft_id 未保持")
    revision2 = _revision_of(draft2, label="改日期")
    bs._check(revision2 > revision1, "改日期后 revision 未增加")
    _assert_draft_dates(draft2, start="2026-10-19", end="2026-10-21", label="改日期")
    bs._check(draft2.get("authoritative_start_date") != "2026-10-12",
              "改日期后旧起始日期残留")
    _assert_draft_time(draft2, start=WORK_START, end=WORK_END, label="改日期")
    _assert_authoritative_duration(draft2, value=3, duration_unit="day", label="改日期")
    _assert_date_sources(draft2, label="改日期")
    _assert_duration_sources(draft2, label="改日期")
    answer_changed = _answer_of(changed.data, label="改日期")
    _assert_answer_matches_draft(answer_changed, draft2, label="改日期")
    bs._check("2026-10-12" not in answer_changed,
              "改日期后 answer 残留旧起始日期")
    bs._check("2026-10-14" not in answer_changed,
              "改日期后 answer 残留旧结束日期")


# --------------------------------------------------------------------------
# 5) 从 ready 仅修改理由 → 同 id、新 revision；权威日期/时长不变，reason 逐字保留且
#    reason_source=user；等待重新确认
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_modify_reason_keeps_authority(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    base = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("请2026年10月12日起3天年假", execution_subject=payload),
    )
    draft_id1, revision1 = _require_ready_three_day(base.data, label="改理由基线")

    task_id = base.task.id
    context_id = base.task.context_id
    changed = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "理由改成去医院复诊",
            context_id=context_id, task_id=task_id, execution_subject=payload,
        ),
    )
    _assert_public_input_required(changed.data, label="改理由")
    draft2 = bs.public_draft(changed.data, label="改理由")

    bs._check(_status_of(draft2, label="改理由") == "ready_for_confirmation",
              "改理由后应等待重新确认")
    bs._check(_draft_id_of(draft2, label="改理由") == draft_id1,
              "改理由后 draft_id 未保持")
    revision2 = _revision_of(draft2, label="改理由")
    bs._check(revision2 > revision1, "改理由后 revision 未增加")
    _assert_draft_dates(draft2, start="2026-10-12", end="2026-10-14", label="改理由")
    _assert_draft_time(draft2, start=WORK_START, end=WORK_END, label="改理由")
    _assert_authoritative_duration(draft2, value=3, duration_unit="day", label="改理由")
    bs._check(draft2.get("reason") == "去医院复诊", "改理由后 reason 未逐字保留")
    bs._check(draft2.get("reason_source") == "user", "改理由后 reason_source 非 user")
    answer_changed = _answer_of(changed.data, label="改理由")
    _assert_answer_matches_draft(answer_changed, draft2, label="改理由")
    bs._check("去医院复诊" in answer_changed, "改理由后 answer 未投影 reason")


# --------------------------------------------------------------------------
# 6) 年假 5 天（余额 4）→ validation_failed + insufficient_balance；
#    不得 ready/confirmed/terminal；权威时长若展示必须 5，不能被压成 1
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_five_day_insufficient_balance(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日起5天年假", execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="余额不足")
    draft = bs.public_draft(data, label="余额不足")

    _assert_not_confirmable_or_terminal(draft, label="余额不足")
    bs._check(_validation_error_code(data, label="余额不足") == "insufficient_balance",
              "余额不足校验码非 insufficient_balance")
    # 权威时长必须按规则计算为 5（5 个已知工作日 12–16），不能被压成 1。
    bs._check(draft.get("authoritative_duration_value") == 5,
              "余额不足权威时长应为 5，不能被压成 1")
    _assert_draft_dates(draft, start="2026-10-12", end="2026-10-16", label="余额不足")
    _assert_answer_business_failure(_answer_of(data, label="余额不足"), data, label="余额不足")


# --------------------------------------------------------------------------
# 7) 0 天 → 不能 ready/confirmed/terminal；validation_error.code=invalid_duration；
#    用户请求时长=0、无合法权威时长；不能被默认成 1 天
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_zero_day_invalid_duration(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日起0天年假", execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="0天")
    draft = bs.public_draft(data, label="0天")

    _assert_not_confirmable_or_terminal(draft, label="0天")
    bs._check(_validation_error_code(data, label="0天") == "invalid_duration",
              "0天校验码非 invalid_duration")
    bs._check(draft.get("duration_value") == 0, "0天用户请求时长应为 0")
    bs._check(draft.get("authoritative_duration_value") is None,
              "0天无合法权威时长，不应为 0 或 1")
    _assert_answer_business_failure(_answer_of(data, label="0天"), data, label="0天")


# --------------------------------------------------------------------------
# 8) 同一员工同 context 不同 task 分别办理 3 天与 1 天 → draft_id 不同，
#    各自续接前后都精确断言字段不串；每轮都通过真实 A2A request_full 并引用 task.id
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_parallel_tasks_isolated(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    context_id = bs.new_context()
    message_three = bs.orchestrator_message(
        "我要请2026年10月12日起3天年假", context_id=context_id, execution_subject=payload,
    )
    message_one = bs.orchestrator_message(
        "我要请2026年10月16日起1天年假", context_id=context_id, execution_subject=payload,
    )
    resp_three, resp_one = await asyncio.gather(
        bs.request_full(probes, "orchestrator", message_three),
        bs.request_full(probes, "orchestrator", message_one),
    )
    _assert_public_input_required(resp_three.data, label="并行3天")
    _assert_public_input_required(resp_one.data, label="并行1天")
    bs._check(resp_three.task.context_id == resp_one.task.context_id,
              "同一 context 的两个 task 未共享 context_id")
    bs._check(resp_three.task.id != resp_one.task.id,
              "同一 context 的两个 task 使用相同 task id")

    # 初轮 3 天：ready、12–14、3 day、假种/时长来源正确。
    draft_three = bs.public_draft(resp_three.data, label="并行3天")
    bs._check(_status_of(draft_three, label="并行3天") == "ready_for_confirmation",
              "并行3天初轮未进入 ready_for_confirmation")
    _assert_type_standard(draft_three, label="并行3天")
    draft_id_three = _draft_id_of(draft_three, label="并行3天")
    revision_three0 = _revision_of(draft_three, label="并行3天")
    _assert_draft_dates(draft_three, start="2026-10-12", end="2026-10-14", label="并行3天")
    _assert_authoritative_duration(draft_three, value=3, duration_unit="day", label="并行3天")
    bs._check((draft_three.get("reason") or "") == "", "并行3天初轮理由应为空")

    # 初轮 1 天：ready、16–16、1 day。
    draft_one = bs.public_draft(resp_one.data, label="并行1天")
    bs._check(_status_of(draft_one, label="并行1天") == "ready_for_confirmation",
              "并行1天初轮未进入 ready_for_confirmation")
    draft_id_one = _draft_id_of(draft_one, label="并行1天")
    revision_one0 = _revision_of(draft_one, label="并行1天")
    _assert_draft_dates(draft_one, start="2026-10-16", end="2026-10-16", label="并行1天")
    _assert_authoritative_duration(draft_one, value=1, duration_unit="day", label="并行1天")
    bs._check((draft_one.get("reason") or "") == "", "并行1天初轮理由应为空")
    bs._check(draft_id_three != draft_id_one, "两个 task 不应共享 draft_id")

    # 续接 3 天：只改理由，字段保持 12–14/3 day，revision 增长，reason 写入。
    resp_three_b = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "理由改成去医院复诊",
            context_id=context_id, task_id=resp_three.task.id, execution_subject=payload,
        ),
    )
    draft_three_b = bs.public_draft(resp_three_b.data, label="并行3天续接")
    bs._check(_status_of(draft_three_b, label="并行3天续接") == "ready_for_confirmation",
              "并行3天续接未保持 ready_for_confirmation")
    bs._check(_draft_id_of(draft_three_b, label="并行3天续接") == draft_id_three,
              "3天续接后 draft_id 未保持")
    revision_three1 = _revision_of(draft_three_b, label="并行3天续接")
    bs._check(revision_three1 > revision_three0, "3天续接后 revision 未增长")
    _assert_draft_dates(draft_three_b, start="2026-10-12", end="2026-10-14", label="并行3天续接")
    _assert_authoritative_duration(draft_three_b, value=3, duration_unit="day", label="并行3天续接")
    bs._check(draft_three_b.get("reason") == "去医院复诊", "3天续接后 reason 未写入")

    # 续接 1 天：改日期 + 写理由，字段变为 20–20/1 day，revision 增长。
    resp_one_b = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "改成2026年10月20日起1天年假，事由医院复诊",
            context_id=context_id, task_id=resp_one.task.id, execution_subject=payload,
        ),
    )
    draft_one_b = bs.public_draft(resp_one_b.data, label="并行1天续接")
    bs._check(_status_of(draft_one_b, label="并行1天续接") == "ready_for_confirmation",
              "并行1天续接未保持 ready_for_confirmation")
    bs._check(_draft_id_of(draft_one_b, label="并行1天续接") == draft_id_one,
              "1天续接后 draft_id 未保持")
    revision_one1 = _revision_of(draft_one_b, label="并行1天续接")
    bs._check(revision_one1 > revision_one0, "1天续接后 revision 未增长")
    _assert_draft_dates(draft_one_b, start="2026-10-20", end="2026-10-20", label="并行1天续接")
    _assert_authoritative_duration(draft_one_b, value=1, duration_unit="day", label="并行1天续接")
    bs._check(draft_one_b.get("reason") == "医院复诊", "1天续接后 reason 未写入")
    bs._check(_draft_id_of(draft_one_b, label="并行1天续接") != draft_id_three,
              "1天与3天 draft_id 不应串")

    # 再续接/读取 3 天：确认 1 天修改未污染 3 天字段。
    resp_three_c = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "先别提交，给我看一下当前申请的日期、天数和理由",
            context_id=context_id, task_id=resp_three.task.id, execution_subject=payload,
        ),
    )
    draft_three_c = bs.public_draft(resp_three_c.data, label="并行3天复查")
    bs._check(_status_of(draft_three_c, label="并行3天复查") == "ready_for_confirmation",
              "并行3天复查未保持 ready_for_confirmation")
    bs._check(_draft_id_of(draft_three_c, label="并行3天复查") == draft_id_three,
              "3天复查 draft_id 未保持")
    _assert_draft_dates(draft_three_c, start="2026-10-12", end="2026-10-14", label="并行3天复查")
    _assert_authoritative_duration(draft_three_c, value=3, duration_unit="day", label="并行3天复查")
    bs._check(draft_three_c.get("reason") == "去医院复诊",
              "3天复查理由被 1 天任务污染")


# --------------------------------------------------------------------------
# 9) 新请求直接说「直接提交不用再问」→ 仍先 ready_for_confirmation，
#    不能未经校验和后续确认直接完成
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_draft_direct_submit_still_ready_for_confirmation(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日起3天年假，直接提交不用再问",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="直接提交")
    bs._check(data.get("status") != "completed", "直接提交不应返回 completed")
    draft = bs.public_draft(data, label="直接提交")

    bs._check(_status_of(draft, label="直接提交") == "ready_for_confirmation",
              "直接提交仍应进入 ready_for_confirmation")
    bs._check(_status_of(draft, label="直接提交") not in _TERMINAL_OR_CONFIRMED,
              "直接提交不应直接 confirmed/terminal")
    _draft_id_of(draft, label="直接提交")
    _revision_of(draft, label="直接提交")
    _assert_draft_dates(draft, start="2026-10-12", end="2026-10-14", label="直接提交")
    _assert_authoritative_duration(draft, value=3, duration_unit="day", label="直接提交")
