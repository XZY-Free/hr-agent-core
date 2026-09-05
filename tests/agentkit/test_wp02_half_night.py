"""WP-02「半天与夜班权威时段/日期」远端验收（TESTS ONLY）。

范围：只覆盖「半天与夜班的权威时段必须来自部署端 Gaia schedule facts，且夜班日期按
跨日事实计算」这一单一业务不变量。只读真实已部署 Orchestrator（HTTPS A2A），
不 import apps/packages/veadk；无本地应用/模型/服务/ASGI/mock/monkeypatch/skip/xfail；
不调用 localhost，不写环境，不读/写云/secret。

发布前提（未来发布 fixture，本文件不修正/不注入任何业务数据；ROOT 会在对应实现发布时给
服务端显式 Gaia stub 的 schedule_overrides 添加固定合成排班，测试自身绝不经环境写入）：
- 2026-10-20：WORK code SCQY01，08:00–17:00，mealBeginTime=12:00，mealEndTime=13:00。
- 2026-10-21：WORK code SCQY01，08:00–17:00，不提供任何 meal/middle 半天边界。
- 2026-10-22：WORK code NIGHT01，19:00–07:00，mealBeginTime=23:00，mealEndTime=00:00。
- 年休假标准名「年休假」、code=A31（packages/hr_domain/constants/leave_rules.py，测试不
  import 业务包，从代码阅读填入固定公开 code）；A31 权限存在，余额 4 day。

当前 v14 RED 原因（真实生产缺电，不制造其它失败）：
- 当前发布 v14 尚无上述 schedule_overrides，故除“无边界拒绝”外，其余场景均因默认白班 /
  缺半天边界 RED：10-20 缺 meal/middle 半天边界 → 半天场景（1/2/3）RED 为
  schedule_detail_insufficient；10-22 非 NIGHT01 跨日夜班 → 夜班全天/半天场景（5/6/7）
  RED（全天 end_date 仍停在 10-22、或时段非 19:00–23:00 / 00:00–07:00 / 00:00–23:00）。
- “无边界拒绝”（场景 4）走的是已实现的 schedule_detail_insufficient 领域路径：当前 v14
  对 10-21（无半天边界）即返回该错误，是本文件中唯一预期无需生产修改的直通场景；其余均
  冻结目标契约，待 ROOT 追加 overrides 后转 GREEN。不要制造其它失败。

冻结行为（目标契约，未追认前除场景 4 外均预期 RED）：
1. 「我要请2026年10月20日上午半天年休假，请先核对并让我确认。」→ ready_for_confirmation，
   权威日期 10-20..10-20、08:00–12:00、0.5 day；时段来源 schedule/schedule，时长来源
   rule/rule；answer 投影这些事实。
2. 同日「下午半天」→ 13:00–17:00、0.5 day，同日 ready。
3. 「2026年10月20日请0.5天年休假」未说上下午 → 领域默认第一半天，08:00–12:00、0.5 day，
   不能用全天（1 day）或中点。
4. 「2026年10月21日上午半天年休假」→ validation_failed / schedule_detail_insufficient；
   无权威时段/时长，不 ready/terminal/submission；answer 展示错误且不请求确认。
5. 「2026年10月22日按当天夜班请全天年休假」→ ready，权威 start_date=10-22、end_date=10-23、
   19:00–07:00、1 day；时段 schedule/schedule。重点：不能把 end_date 停在 10-22。
6. 「2026年10月22日夜班的上半天请年休假」→ ready，10-22..10-22、19:00–23:00、0.5 day。
7. 「2026年10月22日夜班的下半天请年休假」→ ready，权威 start_date=end_date=10-23、
   00:00–07:00、0.5 day。

公共顶层约定：ready_for_confirmation 与 validation_failed 在等待用户动作时均映射
input_required / error_code=input_required；所有 ready 的 draft 必须非 confirmed/terminal、
missing_fields 空、submission 空；均检查 normalized_type_name=年休假 / type_code=A31 /
type_source=normalized_user。结构化 draft 优先，answer 只做投影检查，不从 answer 反推业务事实。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle / ref /
原始响应正文 / env / secret；错误信息不含主体 / oracle / ref / env / secret / 原响应。
HTTP 401/500/timeout 与未知协议错误一律视为失败，绝不当作预期业务拒绝（业务拒绝只认
错误码 / status，协议层 -32602 由 bs.request_reject 单独区分；本切片不用该路径）。

本文件为独立新文件，不修改其它 worker 的生产文件或已有测试；本文件只做语法静态检查，
不运行 pytest。
"""

from __future__ import annotations

import re

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 发布事实：类型/编码（不 import 业务包，从代码阅读填入固定公开 code）。
TYPE_STANDARD = "年休假"
CODE_ANNUAL = "A31"

# 2026-10-20 白班 08:00-17:00，meal 12:00/13:00 → 上午 08:00-12:00、下午 13:00-17:00。
DATE_20 = "2026-10-20"
WORK_START_20 = "08:00"
FIRST_HALF_END_20 = "12:00"
SECOND_HALF_START_20 = "13:00"
WORK_END_20 = "17:00"

# 2026-10-21 白班 08:00-17:00，无半天边界 → 半天拒绝。
DATE_21 = "2026-10-21"

# 2026-10-22 夜班 19:00-07:00，meal 23:00/00:00。
DATE_22 = "2026-10-22"
DATE_23 = "2026-10-23"
NIGHT_START = "19:00"
NIGHT_END = "07:00"
NIGHT_FIRST_HALF_END = "23:00"   # 夜班上半天首端
NIGHT_SECOND_HALF_START = "00:00"  # 夜班下半天落次日

# 来源精确契约。
_DATE_SOURCE_ALLOWED = ("normalized_user", "schedule", "rule")  # 不允许 user/system
_TIME_SOURCE = "schedule"
_DURATION_VALUE_SOURCE = "rule"
_DURATION_UNIT_SOURCE = "rule"

_TERMINAL_OR_CONFIRMED = frozenset({"confirmed", "terminal"})


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


def _assert_type_annual(draft: dict, *, label: str) -> None:
    """必须是「年休假 / A31」且类型来源追溯到用户（normalized_user）。"""
    bs._check(draft.get("normalized_type_name") == TYPE_STANDARD,
              f"{label}标准假名非 年休假")
    bs._check(draft.get("type_code") == CODE_ANNUAL, f"{label}type_code 非 A31")
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


def _assert_time_sources_schedule(draft: dict, *, label: str) -> None:
    """时段来源精确契约：本切片半天/夜班均锚定排班事实，两端都必须是 schedule。"""
    bs._check(draft.get("authoritative_start_time_source") == _TIME_SOURCE,
              f"{label}权威时段开始来源非 schedule")
    bs._check(draft.get("authoritative_end_time_source") == _TIME_SOURCE,
              f"{label}权威时段结束来源非 schedule")


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


def _answer_of(data: dict, *, label: str) -> str:
    answer = data.get("answer")
    bs._check(isinstance(answer, str) and answer, f"{label}公共结果缺少 answer")
    return answer


def _answer_not_confirmation(answer: str, *, label: str) -> None:
    bs._check("确认提交" not in answer and "请核对您的" not in answer,
              f"{label}validation_failed 的 answer 不应请求确认")


def _assert_answer_business_failure(answer: str, data: dict, *, label: str) -> None:
    """校验失败：answer 必须展示对应业务失败（validation_error.message），而非请求确认。"""
    _answer_not_confirmation(answer, label=label)
    inner = bs.public_data(data, label=label)
    validation = inner.get("validation_error")
    bs._check(isinstance(validation, dict), f"{label}未返回 validation_error 对象")
    message = validation.get("message")
    bs._check(isinstance(message, str) and message, f"{label}validation_error.message 为空")
    bs._check(message in answer, f"{label}answer 未展示对应业务失败")


def _answer_day_pattern(value) -> str:
    """边界安全的天数投影正则：接受等值的“1 天”“1.0 天”“0.5 天”。

    服务端摘要用 Python 浮点默认格式化，1.0 会展示为“1.0 天”。用负向后顾
    (?<![0-9.]) 防止把 11 天误当 1 天、把 10.5 天误当 0.5 天；整数倍同时接受
    “X 天”与“X.0 天”（其间可省略空格）。
    """
    if float(value).is_integer():
        return r"(?<![0-9.])%s(?:\.0)?\s*天" % str(int(value))
    return r"(?<![0-9.])%s\s*天" % f"{value:g}"


def _assert_answer_projection(answer: str, draft: dict, *, label: str) -> None:
    """确认摘要必须投影已校验的权威草稿：日期/时段/时长逐字段一致（只做包含式投影）。"""
    bs._check(draft.get("authoritative_start_date") in answer,
              f"{label}answer 未展示权威起始日期")
    bs._check(draft.get("authoritative_end_date") in answer,
              f"{label}answer 未展示权威结束日期")
    bs._check(draft.get("authoritative_start_time") in answer,
              f"{label}answer 未展示权威开始时间")
    bs._check(draft.get("authoritative_end_time") in answer,
              f"{label}answer 未展示权威结束时间")
    unit = draft.get("authoritative_duration_unit")
    bs._check(unit == "day", f"{label}确认摘要投影前置：权威单位应为 day")
    value = draft.get("authoritative_duration_value")
    pattern = _answer_day_pattern(value)
    bs._check(re.search(pattern, answer) is not None,
              f"{label}answer 未展示权威 {value} 天")


# --------------------------------------------------------------------------
# ready 基线：完整校验全部字段 + 来源 + missing 空 + submission 空 + answer 投影。
# --------------------------------------------------------------------------
def _require_ready_annual(data: dict, *, label: str, start_date: str, end_date: str,
                          start_time: str, end_time: str, duration_value,
                          requested_start_date: str | None = None) -> dict:
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(_status_of(draft, label=label) == "ready_for_confirmation",
              f"{label}未进入 ready_for_confirmation")
    bs._check(_status_of(draft, label=label) not in _TERMINAL_OR_CONFIRMED,
              f"{label}不应为 confirmed/terminal")
    _assert_type_annual(draft, label=label)
    _draft_id_of(draft, label=label)
    _revision_of(draft, label=label)
    if requested_start_date is not None:
        bs._check(draft.get("requested_start_date") == requested_start_date,
                  f"{label}requested_start_date 与期望不一致")
    _assert_draft_dates(draft, start=start_date, end=end_date, label=label)
    _assert_authoritative_times(draft, start=start_time, end=end_time, label=label)
    _assert_authoritative_duration(draft, value=duration_value, duration_unit="day", label=label)
    _assert_date_sources(draft, label=label)
    _assert_time_sources_schedule(draft, label=label)
    _assert_duration_sources(draft, label=label)
    bs._check((draft.get("reason") or "") == "", f"{label}理由应为空")
    _assert_missing_empty(data, label=label)
    inner = bs.public_data(data, label=label)
    bs._check(inner.get("submission") is None, f"{label}ready 态不应携带提交结果")
    _assert_answer_projection(_answer_of(data, label=label), draft, label=label)
    return draft


def _assert_time_mode(draft: dict, expected: str, *, label: str) -> None:
    bs._check(draft.get("time_mode") == expected,
              f"{label}time_mode 非 {expected}")


# --------------------------------------------------------------------------
# 1) 2026-10-20 上午半天 → ready，10-20..10-20、08:00-12:00、0.5 day；schedule/rule 来源。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_half_day_20261020_morning_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月20日上午半天年休假，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready_annual(
        data, label="10-20上午半天",
        start_date=DATE_20, end_date=DATE_20,
        start_time=WORK_START_20, end_time=FIRST_HALF_END_20,
        duration_value=0.5, requested_start_date=DATE_20,
    )
    _assert_time_mode(draft, "first_half", label="10-20上午半天")
    bs._check(draft.get("authoritative_duration_value") == 0.5,
              "10-20上午半天权威时长非 0.5")


# --------------------------------------------------------------------------
# 2) 2026-10-20 下午半天 → ready，10-20..10-20、13:00-17:00、0.5 day。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_half_day_20261020_afternoon_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月20日下午半天年休假，请先核对并让我确认。",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready_annual(
        data, label="10-20下午半天",
        start_date=DATE_20, end_date=DATE_20,
        start_time=SECOND_HALF_START_20, end_time=WORK_END_20,
        duration_value=0.5, requested_start_date=DATE_20,
    )
    _assert_time_mode(draft, "second_half", label="10-20下午半天")
    bs._check(draft.get("authoritative_duration_value") == 0.5,
              "10-20下午半天权威时长非 0.5")


# --------------------------------------------------------------------------
# 3) 「2026-10-20 请 0.5 天年休假」未说上/下午 → 领域默认第一半天，08:00-12:00、0.5 day；
#    不能用全天（1 day）或中点。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_bare_half_day_defaults_first_half_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月20日请0.5天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready_annual(
        data, label="裸0.5天",
        start_date=DATE_20, end_date=DATE_20,
        start_time=WORK_START_20, end_time=FIRST_HALF_END_20,
        duration_value=0.5, requested_start_date=DATE_20,
    )
    # 领域默认第一半天：必须 0.5 天（不是全天 1 天），且权威时段不为全天天或中点 12:00 起。
    bs._check(draft.get("authoritative_duration_value") == 0.5,
              "裸0.5天权威时长应为 0.5 天，不能被默认成 1 天")
    bs._check(draft.get("authoritative_duration_value") != 1,
              "裸0.5天不应被当作全天 1 天")
    bs._check(draft.get("authoritative_start_time") == WORK_START_20,
              "裸0.5天权威开始时间应为班次开始 08:00")
    bs._check(draft.get("authoritative_end_time") == FIRST_HALF_END_20,
              "裸0.5天权威结束时间应为第一半天边界 12:00，而非中点")


# --------------------------------------------------------------------------
# 4) 2026-10-21 上午半天（无半天边界）→ validation_failed / schedule_detail_insufficient；
#    无权威时段/时长，不 ready/terminal/submission，answer 展示错误且不请求确认。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_half_day_no_boundary_insufficient(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月21日上午半天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="无半天边界")
    draft = bs.public_draft(data, label="无半天边界")
    bs._check(_status_of(draft, label="无半天边界") == "validation_failed",
              "无半天边界草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label="无半天边界") not in _TERMINAL_OR_CONFIRMED,
              "无半天边界不应进入 confirmed/terminal")
    bs._check(_status_of(draft, label="无半天边界") != "ready_for_confirmation",
              "无半天边界不应误入 ready_for_confirmation")
    _assert_type_annual(draft, label="无半天边界")
    _draft_id_of(draft, label="无半天边界")
    _revision_of(draft, label="无半天边界")
    _assert_time_mode(draft, "first_half", label="无半天边界")
    # 无权威时段/时长：绝不臆造排班时段。
    bs._check(draft.get("authoritative_start_time") is None and draft.get("authoritative_end_time") is None,
              "无半天边界不应臆造权威时段")
    bs._check(draft.get("authoritative_duration_value") is None,
              "无半天边界不应臆造权威时长")
    bs._check(draft.get("authoritative_duration_unit") is None,
              "无半天边界不应臆造权威时长单位")
    bs._check(_validation_error_code(data, label="无半天边界") == "schedule_detail_insufficient",
              "无半天边界校验码非 schedule_detail_insufficient")
    inner = bs.public_data(data, label="无半天边界")
    bs._check(inner.get("submission") is None, "无半天边界失败不应携带 submission")
    _assert_answer_business_failure(_answer_of(data, label="无半天边界"), data,
                                    label="无半天边界")


# --------------------------------------------------------------------------
# 5) 2026-10-22 按当天夜班请全天 → ready，权威 start_date=10-22、end_date=10-23、
#    19:00-07:00、1 day；时段 schedule/schedule。重点：不能把 end_date 留在 10-22。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_night_shift_full_day_cross_day_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月22日按当天夜班请全天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready_annual(
        data, label="夜班全天",
        start_date=DATE_22, end_date=DATE_23,
        start_time=NIGHT_START, end_time=NIGHT_END,
        duration_value=1, requested_start_date=DATE_22,
    )
    _assert_time_mode(draft, "full_day", label="夜班全天")
    # 跨夜班权威结束日期必须跨到次日，绝不能停在 10-22。
    bs._check(draft.get("authoritative_end_date") == DATE_23,
              "夜班全天权威结束日期应为次日 10-23")
    bs._check(draft.get("authoritative_end_date") != DATE_22,
              "夜班全天权威结束日期不应停在 10-22")
    bs._check(draft.get("authoritative_duration_value") == 1,
              "夜班全天权威时长应为 1 天")
    # request 层必须保留当天夜班起始日；全天不另造 requested_end_date。
    bs._check(draft.get("requested_start_date") == DATE_22,
              "夜班全天 requested_start_date 未保留为 10-22")


# --------------------------------------------------------------------------
# 6) 2026-10-22 夜班的上半天 → ready，10-22..10-22、19:00-23:00、0.5 day。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_night_shift_first_half_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月22日夜班的上半天请年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready_annual(
        data, label="夜班上半天",
        start_date=DATE_22, end_date=DATE_22,
        start_time=NIGHT_START, end_time=NIGHT_FIRST_HALF_END,
        duration_value=0.5, requested_start_date=DATE_22,
    )
    _assert_time_mode(draft, "first_half", label="夜班上半天")
    bs._check(draft.get("authoritative_duration_value") == 0.5,
              "夜班上半天权威时长应为 0.5 天")
    bs._check(draft.get("authoritative_end_date") == DATE_22,
              "夜班上半天结束日期应留在 10-22，不跨日")


# --------------------------------------------------------------------------
# 7) 2026-10-22 夜班的下半天 → ready，权威 start_date=end_date=10-23、00:00-07:00、0.5 day。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_night_shift_second_half_cross_day_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月22日夜班的下半天请年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready_annual(
        data, label="夜班下半天",
        start_date=DATE_23, end_date=DATE_23,
        start_time=NIGHT_SECOND_HALF_START, end_time=NIGHT_END,
        duration_value=0.5, requested_start_date=DATE_22,
    )
    _assert_time_mode(draft, "second_half", label="夜班下半天")
    # 下半天落在次日：权威起止日期都必须是 10-23，绝不能留在 10-22。
    bs._check(draft.get("authoritative_start_date") == DATE_23,
              "夜班下半天权威起始日期应为次日 10-23")
    bs._check(draft.get("authoritative_end_date") == DATE_23,
              "夜班下半天权威结束日期应为次日 10-23")
    bs._check(draft.get("authoritative_start_date") != DATE_22,
              "夜班下半天权威起始日期不应留在 10-22")
    bs._check(draft.get("authoritative_duration_value") == 0.5,
              "夜班下半天权威时长应为 0.5 天")
