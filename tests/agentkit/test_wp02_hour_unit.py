"""WP-02「显式小时语义与余额单位隔离」远端验收（TESTS ONLY）。

范围：只覆盖「小时单位请假请求在公共 Orchestrator 上的显式小时语义」这一单一业务不变量；
以及「小时请求与天余额 / 天请求与小时余额」的单位隔离。只读真实 Orchestrator（A2A），
不 import apps/packages/veadk，无本地应用/模型/服务/ASGI/mock/skip/xfail，不调用 localhost。

发布事实（来自已发布 stub 与 ROOT 已读生产代码，本文件不修复/不注入任何业务数据）：
- 调休假标准名「调休假」，HOLIDAY_TYPE_CODE["调休假"]="A02"（packages/hr_domain/constants/leave_rules.py
  ，测试不 import 业务包，从代码阅读填入固定公开 code）。年休假标准名「年休假」code=A31。
- 2026-10-12 为 stub 明确返回 WORK 08:00–17:00 的日期。
- 当前发布 Gaia 余额行：年休假 leaveUnit=day；调休假（A02）在 v11 尚无余额行（行结构未含
  leaveName=调休假/leaveCode=A02/leaveUnit=hour/leaveRemain=4）。ROOT 会在对应实现发布时给
  现有 GAIA_STUB_JSON 追加且只追加该固定合成行（其它字段按既有行结构填 0 / 2026）。
  本测试把【调休假余额行且 leaveUnit=hour / leaveRemain=4】作为发布前提；当前 v11 缺行，
  因此调休假小时流程应真实 RED（balance_unknown），不追求制造其它失败。
- 服务端 Gaia stub 是用户授权的唯一例外，测试不访问云 / env / secret。

冻结行为（目标契约，未追认前当前 v11 预期 RED）：
1. 显式区间 15:00–17:00 请 2 小时调休假 → ready_for_confirmation；同日至 15:00-17:00、2 hour，
   绝不 2day/0.5day；type=调休假/code=A02；时段来源可追溯（用户显式时段不得伪称纯 schedule）。
2. 提前 1 小时下班（调休假）→ 权威 16:00-17:00、1 hour；结束锚来自排班(schedule)、开始由规则计算(rule)，
   时段来源精确为 authoritative_start_time_source=rule、authoritative_end_time_source=schedule。
3. 上班晚到 2 小时（调休假）→ 权威 08:00-10:00、2 hour；开始锚来自排班(schedule)、结束由规则计算(rule)，
   时段来源精确为 authoritative_start_time_source=schedule、authoritative_end_time_source=rule。
4. 显式 15:30 到 17:00 调休 1.5 小时 → 1.5 hour，不四舍五入。
5. 年休假 15:00-17:00 / 2 小时（年假余额 unit=day）→ validation_failed，
   validation_error.code=unit_mismatch，权威仍 2 hour；不能直接余额不足/成功/2day。
6. 调休假全天 1 天（A02 余额 unit=hour）→ validation_failed unit_mismatch，权威 1 day。
7. 调休假 12:00-17:00 / 5 小时、余额 4 hour → validation_failed insufficient_balance，
   权威 5 hour，错误文案/answer 不得写成 day。
8. 「2026-10-12 调休 2 小时」无起止锚 → collecting，missing_fields 必须含 时间/时长，
   不得默认为全天 2 天，也不 ready/terminal。
9. 「2026-10-12 17:00 前请 0 小时调休假」→ validation_failed，冻结领域小时错误 invalid_hours，
   保留 0 语义，绝不改 1。
10.（可选）确认负路径：先建 2 小时 ready，再下一轮确认提交 → 当前边界必须明确
    unsupported_hour，草稿保持 ready_for_confirmation、同 id/revision/2 小时，不 terminal、
    不带成功 submission/leaveDays=0。该边界在 draft_tools.confirm_leave_draft 与
    submit.finalize_leave_submission 有稳定公共映射，故加入。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle /
原始响应正文 / 身份 / secret；不打印凭据 / env / ref。HTTP 401/500/timeout 与未知协议
错误一律视为失败，绝不当作预期业务拒绝。只断言公共结构（data.draft / missing_fields /
validation_error / submission / status / answer），不从 answer 反推业务事实。
"""

from __future__ import annotations

import re

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 发布事实：类型/编码（不 import 业务包，从代码阅读填入固定公开 code）。
TYPE_ADJUST = "调休假"
TYPE_ANNUAL = "年休假"
CODE_ADJUST = "A02"
CODE_ANNUAL = "A31"
# 2026-10-12 为 stub 明确返回 WORK 08:00–17:00 的日期。
DATE = "2026-10-12"
WORK_START = "08:00"
WORK_END = "17:00"

# 来源精确契约：日期权威源只允许 normalized_user/schedule/rule，不允许 user/system。
_DATE_SOURCE_ALLOWED = ("normalized_user", "schedule", "rule")
_DURATION_VALUE_SOURCE = "rule"
_DURATION_UNIT_SOURCE = "rule"

_TERMINAL_OR_CONFIRMED = frozenset({"confirmed", "terminal"})
# 用户显式时段可接受的时间模式（explicit_range / 两端齐备的 explicit_hours 二者之一）。
_EXPLICIT_TIME_MODES = ("explicit_range", "explicit_hours")


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


def _status_of(draft: dict, *, label: str) -> str:
    status = draft.get("status")
    bs._check(isinstance(status, str) and status, f"{label}草稿缺失 status")
    return status


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


def _assert_type_and_code(draft: dict, *, type_name: str, type_code: str, label: str) -> None:
    bs._check(draft.get("normalized_type_name") == type_name,
              f"{label}标准假名非 {type_name}")
    bs._check(draft.get("type_code") == type_code, f"{label}type_code 非 {type_code}")
    bs._check(draft.get("type_source") == "normalized_user",
              f"{label}类型来源未追溯到用户")


def _assert_draft_dates(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_date") == start,
              f"{label}权威起始日期与期望不一致")
    bs._check(draft.get("authoritative_end_date") == end,
              f"{label}权威结束日期与期望不一致")


def _assert_authoritative_times(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_time") == start,
              f"{label}权威开始时间与期望不一致")
    bs._check(draft.get("authoritative_end_time") == end,
              f"{label}权威结束时间与期望不一致")


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


def _assert_time_sources(draft: dict, *, start_source: str, end_source: str, label: str) -> None:
    """时段来源精确契约：只认给定来源，绝不放宽到任意可追溯来源。"""
    bs._check(draft.get("authoritative_start_time_source") == start_source,
              f"{label}权威时段开始来源应为 {start_source}")
    bs._check(draft.get("authoritative_end_time_source") == end_source,
              f"{label}权威时段结束来源应为 {end_source}")


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


def _answer_of(data: dict, *, label: str) -> str:
    answer = data.get("answer")
    bs._check(isinstance(answer, str) and answer, f"{label}公共结果缺少 answer")
    return answer


def _assert_answer_not_confirmation(answer: str, *, label: str) -> None:
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


def _fmt_num(value) -> str:
    return f"{value:g}"


def _assert_no_wrong_day_number(answer: str, value, *, label: str) -> None:
    """answer 不得把小时数误写成天（例如 2 小时 ≠ 2 天）。"""
    pattern = r"(?<![0-9.])%s(?:\.0)?\s*天" % _fmt_num(value)
    bs._check(re.search(pattern, answer) is None,
              f"{label}answer 不应把 {value} 小时误写成天")


def _assert_answer_hour_summary(answer: str, draft: dict, *, label: str) -> None:
    """确认摘要必须投影已校验的权威小时草稿：日期/时段/小时数/单位逐字段一致。"""
    value = draft.get("authoritative_duration_value")
    bs._check(draft.get("authoritative_start_date") in answer,
              f"{label}answer 未展示权威起始日期")
    bs._check(draft.get("authoritative_end_date") in answer,
              f"{label}answer 未展示权威结束日期")
    bs._check(draft.get("authoritative_start_time") in answer,
              f"{label}answer 未展示权威开始时间")
    bs._check(draft.get("authoritative_end_time") in answer,
              f"{label}answer 未展示权威结束时间")
    bs._check(draft.get("authoritative_duration_unit") == "hour",
              f"{label}确认摘要断言前置：权威单位应为 hour")
    pattern = r"(?<![0-9.])%s(?:\.0)?\s*小时" % _fmt_num(value)
    bs._check(re.search(pattern, answer) is not None,
              f"{label}answer 未展示权威 {value} 小时")
    bs._check("确认提交" in answer, f"{label}answer 未请求确认")
    _assert_no_wrong_day_number(answer, value, label=label)


# --------------------------------------------------------------------------
# 小时 ready 基线：完整校验全部字段 + 来源 + 不串成天。
# --------------------------------------------------------------------------
def _require_hour_ready(data: dict, *, label: str, type_name: str, type_code: str,
                        start_time: str, end_time: str, hours) -> tuple[str, int, dict]:
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(_status_of(draft, label=label) == "ready_for_confirmation",
              f"{label}未进入 ready_for_confirmation")
    bs._check(_status_of(draft, label=label) not in _TERMINAL_OR_CONFIRMED,
              f"{label}不应为 confirmed/terminal")
    _assert_type_and_code(draft, type_name=type_name, type_code=type_code, label=label)
    draft_id = _draft_id_of(draft, label=label)
    revision = _revision_of(draft, label=label)
    bs._check(draft.get("requested_start_date") == DATE, f"{label}requested_start_date 不符")
    _assert_draft_dates(draft, start=DATE, end=DATE, label=label)
    _assert_authoritative_times(draft, start=start_time, end=end_time, label=label)
    _assert_authoritative_duration(draft, value=hours, duration_unit="hour", label=label)
    _assert_date_sources(draft, label=label)
    _assert_duration_sources(draft, label=label)
    _assert_missing_empty(data, label=label)
    # 用户请求层时长单位若已给出，必须是 hour，绝不能 day（但模型未在显式区间里填单位时省略）。
    if draft.get("duration_unit") is not None:
        bs._check(draft.get("duration_unit") == "hour",
                  f"{label}用户请求时长单位非 hour")
    # 先权威校验，再把权威草稿投影到 answer 逐字段一致。
    _assert_answer_hour_summary(_answer_of(data, label=label), draft, label=label)
    return draft_id, revision, draft


# --------------------------------------------------------------------------
# 校验失败基线（balance 单位隔离 / 余额不足）：权威值 + 业务失败 answer。
# --------------------------------------------------------------------------
def _require_hour_validation_failed(data: dict, *, label: str, expected_code: str,
                                    start_time: str, end_time: str, value, unit: str) -> dict:
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(_status_of(draft, label=label) == "validation_failed",
              f"{label}草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label=label) not in _TERMINAL_OR_CONFIRMED,
              f"{label}不应为 confirmed/terminal")
    bs._check(_validation_error_code(data, label=label) == expected_code,
              f"{label}校验码非 {expected_code}")
    _assert_draft_dates(draft, start=DATE, end=DATE, label=label)
    _assert_authoritative_times(draft, start=start_time, end=end_time, label=label)
    _assert_authoritative_duration(draft, value=value, duration_unit=unit, label=label)
    _assert_answer_business_failure(_answer_of(data, label=label), data, label=label)
    return draft


# --------------------------------------------------------------------------
# 1) 显式区间 15:00–17:00 请 2 小时调休假 → ready；同日至、2 hour、code=A02、来源可追溯。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_explicit_range_2h_adjust_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日15:00到17:00的调休假，共2小时，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft_id, revision, draft = _require_hour_ready(
        data, label="显式2小时调休",
        type_name=TYPE_ADJUST, type_code=CODE_ADJUST,
        start_time="15:00", end_time="17:00", hours=2,
    )
    bs._check(bool(draft_id) and type(revision) is int, "显式2小时调休草稿身份异常")
    # 时间模式：explicit_range（或两端齐备的 explicit_hours）；用户显式起止精确。
    bs._check(draft.get("time_mode") in _EXPLICIT_TIME_MODES,
              "显式2小时调休 time_mode 非 explicit_range/explicit_hours")
    bs._check(draft.get("requested_start_time") == "15:00",
              "显式2小时调休 requested_start_time 未精确为 15:00")
    bs._check(draft.get("requested_end_time") == "17:00",
              "显式2小时调休 requested_end_time 未精确为 17:00")
    # 用户显式时段不得伪称纯 schedule，也不得 system/不可追溯 user。
    _assert_time_sources(draft, start_source="normalized_user", end_source="normalized_user",
                         label="显式2小时调休")
    # 绝不 2day / 0.5day：权威单位 hour（_require_hour_ready 已断言），值必须 2。
    bs._check(draft.get("authoritative_duration_value") == 2,
              "显式2小时调休权威时长非 2")


# --------------------------------------------------------------------------
# 2) 提前 1 小时下班（调休假）→ 权威 16:00-17:00、1 hour；结束锚来自排班、开始由规则计算。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_early_leave_1h_adjust_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日提前1小时下班的调休假，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft_id, revision, draft = _require_hour_ready(
        data, label="提前1小时下班",
        type_name=TYPE_ADJUST, type_code=CODE_ADJUST,
        start_time="16:00", end_time=WORK_END, hours=1,
    )
    # 结束锚来自排班(schedule)、开始由规则计算(rule)：时段来源精确到值，不得放宽到任意可追溯来源。
    _assert_time_sources(draft, start_source="rule", end_source="schedule",
                         label="提前1小时下班")
    bs._check(draft.get("authoritative_duration_value") == 1,
              "提前1小时下班权威时长非 1")


# --------------------------------------------------------------------------
# 3) 上班晚到 2 小时（调休假）→ 权威 08:00-10:00、2 hour。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_late_arrival_2h_adjust_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日上班晚到2小时的调休假，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft_id, revision, draft = _require_hour_ready(
        data, label="上班晚到2小时",
        type_name=TYPE_ADJUST, type_code=CODE_ADJUST,
        start_time=WORK_START, end_time="10:00", hours=2,
    )
    # 开始锚来自排班(schedule)、结束由规则计算(rule)：时段来源精确到值，不得放宽到任意可追溯来源。
    _assert_time_sources(draft, start_source="schedule", end_source="rule",
                         label="上班晚到2小时")
    bs._check(draft.get("authoritative_duration_value") == 2,
              "上班晚到2小时权威时长非 2")


# --------------------------------------------------------------------------
# 4) 显式 15:30 到 17:00 调休 1.5 小时 → 1.5 hour，不四舍五入。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_explicit_half_hour_15_30_not_rounded(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日15:30到17:00的调休假，共1.5小时，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft_id, revision, draft = _require_hour_ready(
        data, label="1.5小时调休",
        type_name=TYPE_ADJUST, type_code=CODE_ADJUST,
        start_time="15:30", end_time="17:00", hours=1.5,
    )
    bs._check(draft.get("time_mode") in _EXPLICIT_TIME_MODES,
              "1.5小时调休 time_mode 非 explicit_range/explicit_hours")
    _assert_time_sources(draft, start_source="normalized_user", end_source="normalized_user",
                         label="1.5小时调休")
    bs._check(draft.get("authoritative_duration_value") == 1.5,
              "1.5小时调休权威时长非 1.5，被四舍五入")


# --------------------------------------------------------------------------
# 5) 年休假 15:00-17:00 / 2 小时（年假余额 unit=day）→ unit_mismatch，权威仍 2 hour。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_annual_hours_on_day_unit_mismatch(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日15:00到17:00的年休假，共2小时，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_hour_validation_failed(
        data, label="年假小时对天余额",
        expected_code="unit_mismatch",
        start_time="15:00", end_time="17:00", value=2, unit="hour",
    )
    bs._check(draft.get("authoritative_duration_value") == 2,
              "年假小时对天余额权威时长非 2")
    bs._check(draft.get("authoritative_duration_unit") == "hour",
              "年假小时对天余额权威单位非 hour")
    # 不能写成 2day：answer 不得把 2 小时误写成 2 天。
    _assert_no_wrong_day_number(_answer_of(data, label="年假小时对天余额"), 2,
                                label="年假小时对天余额")


# --------------------------------------------------------------------------
# 6) 调休假全天 1 天（A02 余额 unit=hour）→ unit_mismatch，权威 1 day。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_adjust_full_day_on_hour_unit_mismatch(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日全天调休假1天，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_hour_validation_failed(
        data, label="调休全天对小时余额",
        expected_code="unit_mismatch",
        start_time=WORK_START, end_time=WORK_END, value=1, unit="day",
    )
    bs._check(draft.get("authoritative_duration_value") == 1,
              "调休全天对小时余额权威时长非 1")


# --------------------------------------------------------------------------
# 7) 调休假 12:00-17:00 / 5 小时、余额 4 hour → insufficient_balance，权威 5 hour。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_adjust_hours_exceeding_balance_insufficient(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日12:00到17:00的调休假，共5小时，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_hour_validation_failed(
        data, label="调休5小时超余额",
        expected_code="insufficient_balance",
        start_time="12:00", end_time="17:00", value=5, unit="hour",
    )
    bs._check(draft.get("authoritative_duration_value") == 5,
              "调休5小时超余额权威时长非 5")
    # 错误文案/answer 不得写成 day：应指出是小时（工作文案含"小时"），不得写成"5 天"。
    answer = _answer_of(data, label="调休5小时超余额")
    bs._check("小时" in answer, "调休5小时超余额 answer 未用小时说明")
    _assert_no_wrong_day_number(answer, 5, label="调休5小时超余额")


# --------------------------------------------------------------------------
# 8) 「2026-10-12 调休 2 小时」无起止锚 → collecting，missing 含 时间/时长，不默认为全天。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_adjust_hours_no_anchor_collecting(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日调休2小时",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="无起止锚")
    draft = bs.public_draft(data, label="无起止锚")
    bs._check(_status_of(draft, label="无起止锚") == "collecting",
              "无起止锚草稿状态不是 collecting")
    bs._check(_status_of(draft, label="无起止锚") not in _TERMINAL_OR_CONFIRMED,
              "无起止锚不应为 confirmed/terminal")
    bs._check(_status_of(draft, label="无起止锚") != "ready_for_confirmation",
              "无起止锚不应误入 ready_for_confirmation")
    missing = _missing_fields(data, label="无起止锚")
    bs._check("time_or_duration" in missing,
              "无起止锚 missing 应包含 time_or_duration（时间/时长）")
    bs._check("date" not in missing, "无起止锚 missing 不应包含 date")
    _assert_type_and_code(draft, type_name=TYPE_ADJUST, type_code=CODE_ADJUST, label="无起止锚")
    # 不能默认为全天 2 天：未计算权威时长/单位，绝不 late-ready 或 2day。
    bs._check(draft.get("authoritative_duration_value") is None,
              "无起止锚不应臆造权威时长")
    bs._check(draft.get("authoritative_duration_unit") != "day",
              "无起止锚不应默认为全天 2 天")
    bs._check(draft.get("requested_start_date") == DATE, "无起止锚 requested_start_date 不符")


# --------------------------------------------------------------------------
# 9) 「2026-10-12 17:00 前请 0 小时调休假」→ invalid_hours，保留 0 语义，绝不改 1。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_zero_hours_adjust_invalid_hours(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日17:00前0小时调休假，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="0小时")
    draft = bs.public_draft(data, label="0小时")
    bs._check(_status_of(draft, label="0小时") == "validation_failed",
              "0小时草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label="0小时") not in _TERMINAL_OR_CONFIRMED,
              "0小时不应为 confirmed/terminal")
    bs._check(_validation_error_code(data, label="0小时") == "invalid_hours",
              "0小时校验码非 invalid_hours")
    # 保留 0 语义，绝不改 1：用户请求层必须保留 0（显式小时数或时长字段之一），且无合法权威时长。
    bs._check(draft.get("requested_hours") == 0 or draft.get("duration_value") == 0,
              "0小时用户请求时长应保留 0，不能被改成 1")
    bs._check(draft.get("authoritative_duration_value") is None,
              "0小时无合法权威时长，不应为 0 或 1")
    bs._check(draft.get("authoritative_duration_unit") is None,
              "0小时无合法权威时长单位")
    _assert_answer_business_failure(_answer_of(data, label="0小时"), data, label="0小时")


# --------------------------------------------------------------------------
# 10)（可选）确认负路径：先建 2 小时 ready，再下一轮确认提交 → unsupported_hour、
#     草稿保持 ready、同 id/revision/2 小时、不 terminal、不带成功 submission/leaveDays=0。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_confirm_hour_draft_unsupported_keeps_ready(probes, subject_a) -> None:
    payload = _subject_payload(subject_a)
    base = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message(
            "我要请2026年10月12日15:00到17:00的调休假，共2小时，请先核对并让我确认。",
            execution_subject=payload,
        ),
    )
    base_id, base_rev, base_draft = _require_hour_ready(
        base.data, label="小时确认基线",
        type_name=TYPE_ADJUST, type_code=CODE_ADJUST,
        start_time="15:00", end_time="17:00", hours=2,
    )
    task_id = base.task.id
    context_id = base.task.context_id

    nxt = await bs.request_full(
        probes, "orchestrator",
        bs.orchestrator_message("确认提交", context_id=context_id, task_id=task_id,
                                execution_subject=payload),
    )
    _assert_public_input_required(nxt.data, label="小时确认")
    draft = bs.public_draft(nxt.data, label="小时确认")
    # 当前边界：小时最终提交本版本未授权 → 明确 unsupported_hour，草稿保持 ready 非 terminal。
    bs._check(_status_of(draft, label="小时确认") == "ready_for_confirmation",
              "小时确认后应保持 ready_for_confirmation，而非 terminal")
    bs._check(_status_of(draft, label="小时确认") not in _TERMINAL_OR_CONFIRMED,
              "小时确认不应进入 confirmed/terminal")
    bs._check(draft.get("draft_id") == base_id, "小时确认 draft_id 未保持")
    bs._check(draft.get("revision") == base_rev, "小时确认 revision 未保持")
    _assert_authoritative_times(draft, start="15:00", end="17:00", label="小时确认")
    _assert_authoritative_duration(draft, value=2, duration_unit="hour", label="小时确认")
    bs._check(_validation_error_code(nxt.data, label="小时确认") == "unsupported_hour",
              "小时确认边界应明确 unsupported_hour")
    inner = bs.public_data(nxt.data, label="小时确认")
    bs._check(inner.get("submission") is None, "小时确认失败不应携带成功 submission")
    # answer 说明小时提交暂不支持，不得出现 leaveDays=0 / 2 天。
    answer = _answer_of(nxt.data, label="小时确认")
    bs._check("小时" in answer and "不支持" in answer,
              "小时确认 answer 应说明小时提交暂不支持")
    _assert_no_wrong_day_number(answer, 2, label="小时确认")
