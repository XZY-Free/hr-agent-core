"""Leave Draft 服务：标准化、状态机、缺槽位、依赖失效、权威计算。

领域层只做确定性的业务事实计算，不依赖框架。排班/权限/余额数据由调用方从
request-bound HR context 的 Gaia Provider 取得后注入；本服务不访问 session state，
不读取请求方凭据。

WP-02 不变量：权威日期/时段/时长/余额决定必须与显式请求结构和注入的真实排班
事实一致。本服务是单一聚合权威（compute_authoritative）；authoritative_duration /
compute_leave_dates 等只作为单日/日期原语，供旧流程与后续接线切片复用。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from packages.hr_domain.constants.leave_rules import (
    HOLIDAY_TYPE_CODE,
    KNOWN_TYPE_TOKENS,
    LEAVE_GENDER_MAP,
    normalize_type_name,
)
from packages.hr_domain.rules.leave_dates import (
    HORIZON_SAFE_LIMIT_DAYS,
    check_discrete_continuity,
    is_continuous_leave,
)
from packages.hr_domain.rules.leave_duration import (
    CALENDAR_DAY_END,
    CALENDAR_DAY_START,
    _finite_positive,
    _range_hours,
    _valid_time,
)
from packages.hr_domain.schemas.leave_draft import (
    DraftStatus,
    DurationUnit,
    FieldSource,
    HourAnchor,
    LeaveDraftRequest,
    LeaveDraftState,
    MissingFields,
    TimeMode,
)
from packages.hr_domain.schemas.schedule import DayStatus, ScheduleDayTable, build_schedule_table


@dataclass
class DraftResult:
    state: LeaveDraftState
    status: DraftStatus
    missing: MissingFields = field(default_factory=MissingFields)
    error_code: str | None = None
    error_message: str = ""


def new_draft(draft_id: str) -> LeaveDraftState:
    return LeaveDraftState(draft_id=draft_id)


# ---------------------------------------------------------------- 类型冲突
def detect_type_conflict(raw_request: str) -> bool:
    """一次请假申请中是否出现多个不同假期类型。

    WP-02 §13：一次申请只能包含一个假期类型。使用已知假期名/别名的最长非重叠
    匹配，避免"陪产假 ⊃ 产假"这类子串误报。
    """
    if not raw_request:
        return False
    found = set()
    i = 0
    n = len(raw_request)
    while i < n:
        matched = None
        for token in KNOWN_TYPE_TOKENS:  # 已按长度降序
            if raw_request.startswith(token, i):
                matched = token
                break
        if matched is None:
            i += 1
            continue
        canonical = normalize_type_name(matched) or matched
        found.add(canonical)
        i += len(matched)
        if len(found) > 1:
            return True
    return len(found) > 1


# ---------------------------------------------------------------- 标准化
def normalize_type(draft: LeaveDraftState, raw_type: str | None) -> None:
    """标准化假期类型；类型变更即失效依赖（permission/gender/balance/确认）。

    无效替换必须清除旧的 normalized_type_name / type_code / type_source，并失效权威域。
    """
    if not raw_type:
        return
    name = normalize_type_name(raw_type)
    draft.raw_type_expression = raw_type
    if name is None:
        draft.normalized_type_name = None
        draft.type_code = None
        draft.type_source = None
        draft.validation_errors.append(f"未知假期类型：{raw_type}")
    else:
        draft.normalized_type_name = name
        draft.type_code = HOLIDAY_TYPE_CODE.get(name)
        draft.type_source = FieldSource.NORMALIZED_USER
    # 类型变更：失效权限/性别/余额/确认，并清理旧的权威域。
    _invalidate_after_type_change(draft)


def _invalidate_after_type_change(draft: LeaveDraftState) -> None:
    # 类型决定 duration-unit 兼容性与确认摘要；日期原值保留但需重新验证。
    draft.invalidation_reason = "假期类型已变更"
    draft.validation_errors = [
        e for e in draft.validation_errors if e.startswith("未知假期类型")
    ]
    _clear_authority(draft)


def _clear_authority(draft: LeaveDraftState) -> None:
    draft.authoritative_start_date = None
    draft.authoritative_end_date = None
    draft.authoritative_start_time = None
    draft.authoritative_end_time = None
    draft.authoritative_duration_value = None
    draft.authoritative_duration_unit = None
    draft.authoritative_start_date_source = None
    draft.authoritative_end_date_source = None
    draft.authoritative_start_time_source = None
    draft.authoritative_end_time_source = None
    draft.authoritative_duration_value_source = None
    draft.authoritative_duration_unit_source = None


# ---------------------------------------------------------------- 缺槽位
def compute_missing_fields(draft: LeaveDraftState) -> MissingFields:
    """由结构化"请求输入"判定缺失；input_required 的唯一状态来源。

    面向用户是否已提供足够输入，而非权威域是否已计算。
    """
    return MissingFields(
        type_name=not draft.normalized_type_name,
        date=not draft.requested_start_date,
        time_or_duration=not _requested_time_complete(draft),
        reason=False,  # 理由非必填；未提供则保留空，不臆造
    )


def _requested_hour_quantity(draft: LeaveDraftState) -> float | None:
    """用户声明的小时数量：requested_hours 优先；否则仅当 duration_unit=hour 时取 duration_value。

    day 时长绝不当作小时数量（不读天为时）；缺失/无法确定返回 None。
    """
    if draft.requested_hours is not None:
        return draft.requested_hours
    if draft.duration_unit is DurationUnit.HOUR and draft.duration_value is not None:
        return draft.duration_value
    return None


def _requested_time_complete(draft: LeaveDraftState) -> bool:
    """「时间/时长」槽位是否已表达。不再用 `duration_value is not None` 一刀切吞掉小时锚点语义。

    - 全天/半天沿用旧语义；
    - 显式区间：两端都有才完整；
    - 显式小时：必须有一个有限小时数量，且有一个显式边界或 hour_anchor 锚点（否则即便给了
      2 小时也只是“还差锚点”）；0 小时算已表达，交给领域判 invalid_hours；
    - 无显式时间模式：只认「非小时」时长（天时长/未给单位）为已表达，小时走 explicit_hours。
    """
    m = draft.time_mode
    if m is None:
        return draft.duration_value is not None and draft.duration_unit is not DurationUnit.HOUR
    if m is TimeMode.FULL_DAY:
        # 某日全天：已知开始日期 + full_day 即表达完整。
        return bool(draft.requested_start_date)
    if m in (TimeMode.FIRST_HALF, TimeMode.SECOND_HALF):
        return True
    if m is TimeMode.EXPLICIT_RANGE:
        return bool(draft.requested_start_time and draft.requested_end_time)
    if m is TimeMode.EXPLICIT_HOURS:
        quantity = _requested_hour_quantity(draft)
        if quantity is None:
            return False
        return bool(
            draft.requested_start_time or draft.requested_end_time or draft.hour_anchor
        )
    return False


# ---------------------------------------------------------------- 权威计算
def compute_authoritative(
    draft: LeaveDraftState,
    *,
    table: ScheduleDayTable,
    calendar_duration: float = 1.0,
    workdays_requested: int = 1,
    requested_segments: list[str] | None = None,
) -> DraftResult:
    """根据标准化后的草稿计算权威日期/时段/时长并校验排班、连续性。

    仅在时间表达与日期都已确定时调用；返回权威 start/end/time/duration。
    计算成功才原子写入权威字段，并同步 draft.status。
    """
    if not draft.normalized_type_name or not draft.requested_start_date:
        return _result(draft, DraftStatus.COLLECTING)
    if not _requested_time_complete(draft):
        return _result(draft, DraftStatus.COLLECTING)

    time_mode = draft.time_mode
    if time_mode in (TimeMode.EXPLICIT_RANGE, TimeMode.EXPLICIT_HOURS):
        return _compute_hour(draft, table)
    if time_mode in (TimeMode.FIRST_HALF, TimeMode.SECOND_HALF):
        return _compute_half(draft, table)
    return _compute_full_day(draft, table, requested_segments)


# ---------------------------------------------------------------- 小时模式
def _compute_hour(draft: LeaveDraftState, table: ScheduleDayTable) -> DraftResult:
    """小时权威计算：显式小时 / 显式区间，单位 hour，来源精确到值。

    冲突优先级：用户声明的小时数量 <=0 / 非有限 → invalid_hours（不解释任何模型排出的区间）；
    显式区间/两端都给 → 以区间实算为准（双方 NORMALIZED_USER）；单边 → 用户边 NORMALIZED_USER、
    推导边 RULE；hour_anchor=shift_end → end=排班结束(SCHEDULE)、start=end-hours(RULE)；
    hour_anchor=shift_start → start=排班开始(SCHEDULE)、end=start+hours(RULE)。
    排班/区间/夜班安全校验保持 fail closed。
    """
    is_range = draft.time_mode is TimeMode.EXPLICIT_RANGE
    quantity = _requested_hour_quantity(draft)
    start_t, end_t = draft.requested_start_time, draft.requested_end_time

    # 用户声明的非正/非有限小时数优先失效，绝不解释成非法时间范围或排班冲突。
    if quantity is not None and not _finite_positive(quantity):
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="invalid_hours",
                       error_message="小时数必须大于 0 且为有限数值。")

    fact = table.fact(draft.requested_start_date)
    if fact is None or not fact.start_time or not fact.end_time:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="schedule_unknown",
                       error_message="排班证据不足，无法确认时段。")
    if fact.is_rest:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="rest_day",
                       error_message="该日期是正常休息日，不需要请假。")

    if is_range or (start_t and end_t):
        # 两边用户显式（explicit_range，或 explicit_hours 但两端都给）：来源 NORMALIZED_USER；
        # 权威时长按区间实算，声明时长与区间不一致时以区间为准。
        if not start_t or not end_t:
            return _result(draft, DraftStatus.COLLECTING)
        hours = _range_hours(start_t, end_t)
        if hours is None or hours <= 0:
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="invalid_time_range",
                           error_message="时间范围无效。")
        if not _range_fits_shift(fact, start_t, end_t):
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="time_out_of_shift",
                           error_message="所选时段超出班次，请核对。")
        a_start, a_end, a_value = start_t, end_t, hours
        src_start, src_end = FieldSource.NORMALIZED_USER, FieldSource.NORMALIZED_USER
    elif start_t:
        # 单边界（start 用户显式）无锚：start NORMALIZED_USER，end 由规则推导 RULE。
        if quantity is None:
            return _result(draft, DraftStatus.COLLECTING)
        start_min = _to_minutes(start_t)
        if start_min is None:
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="invalid_time_range", error_message="时间无效。")
        end_min = start_min + int(round(quantity * 60))
        a_end = _minutes_to_str(end_min)
        if not _range_fits_shift(fact, start_t, a_end):
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="time_out_of_shift",
                           error_message="所选时段超出班次，请核对。")
        a_start, a_value = start_t, quantity
        src_start, src_end = FieldSource.NORMALIZED_USER, FieldSource.RULE
    elif end_t:
        # 单边界（end 用户显式）无锚：end NORMALIZED_USER，start 由规则推导 RULE。
        if quantity is None:
            return _result(draft, DraftStatus.COLLECTING)
        end_min = _to_minutes(end_t)
        if end_min is None:
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="invalid_time_range", error_message="时间无效。")
        start_min = end_min - int(round(quantity * 60))
        a_start = _minutes_to_str(start_min)
        if not _range_fits_shift(fact, a_start, end_t):
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="time_out_of_shift",
                           error_message="所选时段超出班次，请核对。")
        a_end, a_value = end_t, quantity
        src_start, src_end = FieldSource.RULE, FieldSource.NORMALIZED_USER
    elif draft.hour_anchor is HourAnchor.SHIFT_END:
        # 下班锚点：end=排班结束(SCHEDULE)，start=end-hours(RULE)。无显式时间。
        if quantity is None:
            return _result(draft, DraftStatus.COLLECTING)
        end_min = _to_minutes(fact.end_time)
        start_min = end_min - int(round(quantity * 60))
        a_start = _minutes_to_str(start_min)
        a_end = fact.end_time
        if not _range_fits_shift(fact, a_start, a_end):
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="time_out_of_shift",
                           error_message="所选时段超出班次，请核对。")
        a_value = quantity
        src_start, src_end = FieldSource.RULE, FieldSource.SCHEDULE
    elif draft.hour_anchor is HourAnchor.SHIFT_START:
        # 上班锚点：start=排班开始(SCHEDULE)，end=start+hours(RULE)。无显式时间。
        if quantity is None:
            return _result(draft, DraftStatus.COLLECTING)
        start_min = _to_minutes(fact.start_time)
        end_min = start_min + int(round(quantity * 60))
        a_start = fact.start_time
        a_end = _minutes_to_str(end_min)
        if not _range_fits_shift(fact, a_start, a_end):
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="time_out_of_shift",
                           error_message="所选时段超出班次，请核对。")
        a_value = quantity
        src_start, src_end = FieldSource.SCHEDULE, FieldSource.RULE
    else:
        # 无边界且无锚点：本应被 completeness 拦截，安全收集。
        return _result(draft, DraftStatus.COLLECTING)

    # 跨天偏移相对班次原点
    start_off = _time_day_offset(fact, a_start)
    end_off = _time_day_offset(fact, a_end)
    _write_authority(
        draft,
        start_date=_add_days(draft.requested_start_date, start_off),
        end_date=_add_days(draft.requested_start_date, end_off),
        start_time=a_start, end_time=a_end,
        duration_value=a_value, duration_unit=DurationUnit.HOUR,
        start_date_source=FieldSource.NORMALIZED_USER,
        end_date_source=FieldSource.NORMALIZED_USER,
        start_time_source=src_start,
        end_time_source=src_end,
    )
    return _result(draft, DraftStatus.READY_FOR_VALIDATION)


# ---------------------------------------------------------------- 半天模式
def _compute_half(draft: LeaveDraftState, table: ScheduleDayTable) -> DraftResult:
    is_first = draft.time_mode is TimeMode.FIRST_HALF
    fact = table.fact(draft.requested_start_date)
    insufficient = _result(
        draft, DraftStatus.VALIDATION_FAILED,
        error_code="schedule_detail_insufficient",
        error_message="当前排班未提供半天边界，暂时无法确定半天排班时段。",
    )
    if fact is None or not fact.start_time or fact.is_rest:
        return insufficient
    if is_first:
        end_t = fact.half_day_boundaries[0]
        if not end_t:
            return insufficient
        start_t = fact.start_time
    else:
        start_t = fact.half_day_boundaries[1]
        if not start_t:
            return insufficient
        end_t = fact.end_time or CALENDAR_DAY_END
    # 第二个半天在夜班（00:00-07:00）落在次日，偏移相对班次原点
    off = _time_day_offset(fact, start_t)
    _write_authority(
        draft,
        start_date=_add_days(draft.requested_start_date, off),
        end_date=_add_days(draft.requested_start_date, off),
        start_time=start_t, end_time=end_t,
        duration_value=0.5, duration_unit=DurationUnit.DAY,
    )
    return _result(draft, DraftStatus.READY_FOR_VALIDATION)


# ---------------------------------------------------------------- 全天聚合
def _compute_full_day(draft: LeaveDraftState, table: ScheduleDayTable,
                      requested_segments: list[str] | None) -> DraftResult:
    continuous = is_continuous_leave(draft.normalized_type_name or "")
    plan, err = _resolve_full_day_plan(draft, table, requested_segments)
    if err:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code=err[0], error_message=err[1])

    # 校验并聚合每天贡献，同时确定首末时段
    duration = 0.0
    first_start = None
    last_end = None
    first_fact = None
    last_fact = None
    for ent in plan:
        d, half = ent["date"], ent.get("half")
        fact = table.fact(d)
        if fact is None:
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="schedule_unknown",
                           error_message="排班证据不足，无法确认工作日。")
        if fact.is_rest:
            if not continuous:
                return _result(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="rest_day",
                               error_message="该日期是正常休息日，不需要请假。")
            start_t, end_t = CALENDAR_DAY_START, CALENDAR_DAY_END
            contribution = 0.5 if half else 1.0
        elif half == "first":
            end_t = fact.half_day_boundaries[0]
            if not end_t:
                return _result(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="schedule_detail_insufficient",
                               error_message="当前排班未提供半天边界，暂时无法确定半天排班时段。")
            start_t = fact.start_time or CALENDAR_DAY_START
            contribution = 0.5
        elif half == "second":
            start_t = fact.half_day_boundaries[1]
            if not start_t:
                return _result(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="schedule_detail_insufficient",
                               error_message="当前排班未提供半天边界，暂时无法确定半天排班时段。")
            end_t = fact.end_time or CALENDAR_DAY_END
            contribution = 0.5
        else:
            # 明确 WORK 但缺时段证据：fail closed，绝不用 canonical 08–18 兜底成功。
            if not fact.start_time or not fact.end_time:
                return _result(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="schedule_unknown",
                               error_message="该日期排班缺少时段证据，暂无法确认，请稍后再试。")
            start_t = fact.start_time
            end_t = fact.end_time
            contribution = 1.0
        duration += contribution
        if first_start is None:
            first_start = start_t
            first_fact = fact
        last_end = end_t
        last_fact = fact

    # 权威日期按班次时间跨日：用首日 fact + 权威开始时间、末日 fact + 权威结束时间，
    # 复用 _time_day_offset 处理跨天夜班；白班/休息日偏移为 0，日期不变。
    start_offset = _time_day_offset(first_fact, first_start)
    end_offset = _time_day_offset(last_fact, last_end)
    _write_authority(
        draft,
        start_date=_add_days(plan[0]["date"], start_offset),
        end_date=_add_days(plan[-1]["date"], end_offset),
        start_time=first_start, end_time=last_end,
        duration_value=duration, duration_unit=DurationUnit.DAY,
    )
    return _result(draft, DraftStatus.READY_FOR_VALIDATION)


def _resolve_full_day_plan(draft: LeaveDraftState, table: ScheduleDayTable,
                           requested_segments: list[str] | None):
    """返回 (plan, None) 或 (None, (error_code, error_message))。"""
    continuous = is_continuous_leave(draft.normalized_type_name or "")
    intent = draft.duration_value
    segs = requested_segments or (
        list(draft.requested_date_segments) if draft.requested_date_segments else None
    )
    start = draft.requested_start_date
    end = draft.requested_end_date

    if intent is not None:
        if not _finite_positive(intent):
            return None, ("invalid_duration", "请假天数必须大于 0 且为有限数值。")
        frac = intent - math.floor(intent)
        if frac not in (0.0, 0.5):
            return None, ("invalid_duration", "请假时长仅支持整天或半天。")

    if segs and len(set(segs)) > 1:
        return _discrete_plan(sorted(set(segs)), table, continuous)
    if end and end != start:
        return _range_plan(start, end, table, continuous)
    # 单日（start==end 或仅给 start 或单个离散日期）且为全天 full_day：本身即完整 1 天，
    # 不必要求用户另给 duration_value=1。用户显式给末项（0）仍由上方 intent 非 None 分支判
    # invalid_duration；3/5 天照常累计；多日范围已在上面走 range_plan，不会被此默认压成 1。
    if intent is None:
        intent = 1.0
    return _duration_plan(start, table, continuous, intent)


def _discrete_plan(segs: list[str], table: ScheduleDayTable, continuous: bool):
    # 中间间隔只允许已知休息日；WORK → 不连续；UNKNOWN → 不确定
    ok, err = check_discrete_continuity(segs, table)
    if err is not None:
        return None, (err, _continuity_message(err))
    plan = []
    for d in segs:
        status = table.day(d)
        if status is DayStatus.UNKNOWN:
            return None, ("schedule_unknown_for_continuity",
                          "中间日期排班未知，暂时无法确认是否连续，请稍后再试。")
        if status is DayStatus.REST and not continuous:
            return None, ("rest_day", "该日期是正常休息日，不需要请假。")
        plan.append({"date": d, "half": None})
    if not plan:
        return None, ("invalid_duration", "未能确定任何请假日期。")
    return plan, None


def _range_plan(start: str, end: str, table: ScheduleDayTable, continuous: bool):
    if continuous:
        n = (_parse_date(end) - _parse_date(start)).days + 1
        return [{"date": _add_days(start, i), "half": None} for i in range(n)], None
    plan = []
    cur = _parse_date(start)
    while cur <= _parse_date(end):
        d = _iso(cur)
        status = table.day(d)
        if status is DayStatus.UNKNOWN:
            return None, ("schedule_unknown", "排班在所需日期未知，无法确认。")
        if status is DayStatus.WORK:
            plan.append({"date": d, "half": None})
        cur += timedelta(days=1)
    if not plan:
        return None, ("rest_day", "所选日期范围内没有工作日。")
    return plan, None


def _duration_plan(start: str, table: ScheduleDayTable, continuous: bool, intent):
    if intent is None:
        return None, ("invalid_duration", "缺少请假天数。")
    if continuous:
        whole = math.floor(intent)
        has_half = (intent - whole) == 0.5
        n_days = whole + (1 if has_half else 0)
        plan = []
        for i in range(n_days):
            half = "first" if (has_half and i == n_days - 1) else None
            plan.append({"date": _add_days(start, i), "half": half})
        return plan, None
    return _duration_plan_skip(start, table, intent)


def _duration_plan_skip(start: str, table: ScheduleDayTable, intent):
    status = table.day(start)
    if status is DayStatus.UNKNOWN:
        return None, ("schedule_unknown", "排班证据不足，无法确认工作日。")
    if status is DayStatus.REST:
        if intent <= 1.0:
            return None, ("rest_day", "该日期是正常休息日，不需要请假。")
        eff = _next_known_workday_no_skip(start, table)
        if eff is None:
            return None, ("schedule_unknown", "排班证据不足，无法确认工作日。")
    else:
        eff = start

    plan = []
    remaining = intent
    cur = _parse_date(eff)
    for _ in range(HORIZON_SAFE_LIMIT_DAYS):
        d = _iso(cur)
        status = table.day(d)
        if status is DayStatus.UNKNOWN:
            return None, ("schedule_unknown", "排班在需要日期未知，不能跳过。")
        if status is DayStatus.WORK:
            if remaining >= 1.0:
                plan.append({"date": d, "half": None})
                remaining -= 1.0
                if remaining == 0:
                    break
            else:
                plan.append({"date": d, "half": "first"})  # 余量 0.5 → 默认第一个半天
                break
        cur += timedelta(days=1)
    else:
        return None, ("schedule_horizon_exceeded", "排班范围不足，暂时无法确认所需工作日。")
    if not plan:
        return None, ("invalid_duration", "未能确定任何请假日期。")
    return plan, None


def _next_known_workday_no_skip(start: str, table: ScheduleDayTable) -> str | None:
    cur = _parse_date(start)
    for _ in range(HORIZON_SAFE_LIMIT_DAYS):
        d = _iso(cur)
        status = table.day(d)
        if status is DayStatus.WORK:
            return d
        if status is DayStatus.UNKNOWN:
            return None
        cur += timedelta(days=1)
    return None


# ---------------------------------------------------------------- 权限→性别→余额
def validate_permission_gender_balance(
    draft: LeaveDraftState,
    *,
    allowed_types: list[str],
    sex: str | None,
    balance: list[dict] | None,
) -> DraftResult:
    """权限 → 性别 → 余额校验；余额使用 authoritative 时长与单位匹配。"""
    if not draft.normalized_type_name:
        return _result(draft, DraftStatus.COLLECTING)

    if draft.type_code is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="no_permission",
                       error_message="未知假期类型，无法申请。")

    if draft.normalized_type_name not in allowed_types:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="no_permission",
                       error_message="您暂无权限申请该类型假期，请核对后重试或咨询 HR。")

    if draft.normalized_type_name in LEAVE_GENDER_MAP:
        if sex is None:
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="gender_unknown",
                           error_message="该假期需要确认员工性别。")
        expected = LEAVE_GENDER_MAP[draft.normalized_type_name]
        if expected != sex:
            label = "男性" if expected == "M" else "女性"
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="gender_mismatch",
                           error_message=f"该假期仅限{label}员工申请。")

    # 权威时长完整且单位明确
    if draft.authoritative_duration_unit is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="duration_unit_unknown",
                       error_message="无法确定请假时长单位。")
    unit = draft.authoritative_duration_unit
    requested = draft.authoritative_duration_value
    if requested is None or not _finite_positive(requested):
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="duration_value_unknown",
                       error_message="无法确定请假时长。")

    # 余额：匹配类型，单位一致，数值有限非负
    if balance is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unknown",
                       error_message="假期余额暂时无法确认。")
    row = next((it for it in balance if it.get("leave_name") == draft.normalized_type_name), None)
    if row is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unknown",
                       error_message="假期余额暂时无法确认。")
    row_unit = row.get("unit")
    if row_unit is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unit_unknown",
                       error_message="余额单位缺失，无法比较。")
    row_unit = _normalize_unit(row_unit)
    if row_unit is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unit_unknown",
                       error_message="余额单位无法识别。")
    if row_unit is not unit:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="unit_mismatch",
                       error_message="请假时长单位与余额单位不一致。")
    remain_raw = row.get("remain")
    if remain_raw is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unknown",
                       error_message="假期余额暂时无法确认。")
    try:
        remain = float(remain_raw)
    except (TypeError, ValueError):
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unknown",
                       error_message="假期余额暂时无法确认。")
    if not math.isfinite(remain) or remain < 0:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="balance_unknown",
                       error_message="假期余额暂时无法确认。")

    label = "小时" if unit is DurationUnit.HOUR else "天"
    if remain < requested:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="insufficient_balance",
                       error_message=f"您的假期余额为 {remain} {label}，不足以申请 {requested} {label}。")

    draft.validation_errors = []
    return _result(draft, DraftStatus.READY_FOR_CONFIRMATION)


def _normalize_unit(value) -> DurationUnit | None:
    if isinstance(value, DurationUnit):
        return value
    if value == DurationUnit.DAY.value:
        return DurationUnit.DAY
    if value == DurationUnit.HOUR.value:
        return DurationUnit.HOUR
    return None


# ---------------------------------------------------------------- 内部工具
def _result(draft, status, *, error_code=None, error_message="", missing=None):
    draft.status = status
    # 成功态（无错误码）清掉旧错误；失败态记录结构化错误类别，供 read-only / reason-only 保留。
    if error_code:
        draft.status_error_code = error_code
        draft.status_error_message = error_message
    else:
        draft.status_error_code = None
        draft.status_error_message = ""
    return DraftResult(
        draft, status,
        missing=missing if missing is not None else compute_missing_fields(draft),
        error_code=error_code, error_message=error_message,
    )


def _write_authority(draft, *, start_date, end_date, start_time, end_time,
                     duration_value, duration_unit,
                     start_date_source=FieldSource.SCHEDULE,
                     end_date_source=FieldSource.SCHEDULE,
                     start_time_source=FieldSource.SCHEDULE,
                     end_time_source=FieldSource.SCHEDULE,
                     duration_value_source=FieldSource.RULE,
                     duration_unit_source=FieldSource.RULE):
    draft.authoritative_start_date = start_date
    draft.authoritative_end_date = end_date
    draft.authoritative_start_time = start_time
    draft.authoritative_end_time = end_time
    draft.authoritative_duration_value = duration_value
    draft.authoritative_duration_unit = duration_unit
    draft.authoritative_start_date_source = start_date_source
    draft.authoritative_end_date_source = end_date_source
    draft.authoritative_start_time_source = start_time_source
    draft.authoritative_end_time_source = end_time_source
    draft.authoritative_duration_value_source = duration_value_source
    draft.authoritative_duration_unit_source = duration_unit_source


def _parse_date(value: str) -> date:
    y, m, d = value.split("-")
    return date(int(y), int(m), int(d))


def _iso(value: date) -> str:
    return value.isoformat()


def _add_days(iso_date: str, n: int) -> str:
    return (_parse_date(iso_date) + timedelta(days=n)).isoformat()


def _to_minutes(time_str: str) -> int | None:
    if not _valid_time(time_str):
        return None
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def _minutes_to_str(total_min: int) -> str:
    total_min %= 1440
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def _range_fits_shift(fact, start_t: str, end_t: str) -> bool:
    if not fact.start_time or not fact.end_time:
        return False
    s, e = _to_minutes(fact.start_time), _to_minutes(fact.end_time)
    if s is None or e is None:
        return False
    if e < s:
        e += 1440
    rs, re = _to_minutes(start_t), _to_minutes(end_t)
    if rs is None or re is None:
        return False
    if re < rs:
        re += 1440
    # 区间必须落在班次窗口内
    return rs >= s and re <= e


def _time_day_offset(fact, time_str: str) -> int:
    """时间相对班次原点所在日的偏移天数（处理跨天夜班）。"""
    if fact is None or not fact.start_time or not fact.end_time:
        return 0
    s = _to_minutes(fact.start_time)
    e = _to_minutes(fact.end_time)
    t = _to_minutes(time_str)
    if s is None or e is None or t is None:
        return 0
    if e < s:  # 跨天夜班
        return 1 if t < s else 0
    return 0


def _continuity_message(err_code: str) -> str:
    if err_code == "discontinuous_workday_gap":
        return "您选择的日期中间存在工作日间隔，请拆开提交。"
    return "中间日期排班未知，暂时无法确认是否连续，请稍后再试。"


# --------------------------------------------------------------------------
# 面向模型工具的高层编排（草稿变更由领域服务管理）。
# --------------------------------------------------------------------------
_SCHEDULE_WINDOW_DAYS = 30  # 领域一次排班查询窗口的最大自然日数（含首尾）；provider size=30，同界。


def _to_time_mode(value: str | None) -> TimeMode | None:
    if value is None:
        return None
    try:
        return TimeMode(value)
    except ValueError:
        return None


def _to_duration_unit(value: str | None) -> DurationUnit | None:
    if value is None:
        return None
    try:
        return DurationUnit(value)
    except ValueError:
        return None


_MODIFICATION_MARKERS = ("改成", "换成", "变更", "调整为", "改为", "换成", "还是", "改")
_COMBINATION_MARKERS = ("加", "和", "同时", "、", "跟", "与", "两种", "再请")


def _contains_combination(text: str) -> bool:
    return any(m in text for m in _COMBINATION_MARKERS)


def _contains_modification(text: str) -> bool:
    return any(m in text for m in _MODIFICATION_MARKERS)


def _has_type_conflict(user_text: str) -> bool:
    """多假种冲突只对"本次组合请求"判；"把年假改成病假/改日期"这类修改不算合并。"""
    probe = user_text or ""
    if not _contains_combination(probe):
        return False
    if _contains_modification(probe):
        # 含"改成/改/换成…"通常是修改已有类型，而非一次申请两种类型。
        return False
    return detect_type_conflict(probe)


def _apply_reason(draft: LeaveDraftState, request: LeaveDraftRequest,
                  provided: set[str], user_text: str) -> bool:
    """理由：empty/None 表示清空；非空必须能在本轮用户原文中追溯，否则不进入草稿。"""
    if "reason" not in provided:
        return False
    v = request.reason
    if v is None or v == "":
        if draft.reason is not None or draft.reason_source is not None:
            draft.reason = None
            draft.reason_source = None
            return True
        return False
    # 非空理由必须可在用户原文中逐字找到，禁止无来源理由进入草稿。
    if user_text and v in user_text:
        if draft.reason != v:
            draft.reason = v
            draft.reason_source = FieldSource.USER
            return True
        if draft.reason_source is not FieldSource.USER:
            draft.reason_source = FieldSource.USER
            return True
        return False
    # 无原文来源：忽略本次理由，保持旧值，不进入草稿。
    return False


# --------------------------------------------------------------------------
# duration-driven 判定：用户表达「从/由某日起（开始）请 N 天」且只给一个起算日期时，
# 结束日应由天数/连续自然日或跳休排班规则计算，模型推算的 requested_end_date 不是用户事实。
# 只做字段来源/日期表达归一化，绝不用于路由。
# --------------------------------------------------------------------------
_DATE_TOKEN_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日"
)
_RELATIVE_DATE_RE = re.compile(r"大后天|后天|明天|今天")
_WEEK_NEXT_RE = re.compile(r"下周[日一二三四五六天]")
# 区间/离散连接词：一旦出现即视为用户给出了第二个日期事实，不得当作单日起算的时长请求。
_DATE_SERIES_CONNECTORS = ("到", "至", "和", "及", "以及", "、", "~", "～", "－", "—")


def _norm_date_anchor(tok: str) -> str:
    """把日期 token 归一化为可判重的锚点；无年份日期仅作「又是一个日期」标记。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", tok)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日$", tok)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{1,2})月(\d{1,2})日$", tok)
    if m:
        return f"-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return tok


def _extract_date_anchors(text: str) -> list[str]:
    """提取用户原文中的日期/相对日期锚点，去重；用于判断是否只有一个起算日期。"""
    anchors: list[str] = []
    for m in _DATE_TOKEN_RE.finditer(text):
        anchors.append(_norm_date_anchor(m.group(0)))
    for m in _RELATIVE_DATE_RE.finditer(text):
        anchors.append(m.group(0))
    for m in _WEEK_NEXT_RE.finditer(text):
        anchors.append(m.group(0))
    seen: set[str] = set()
    out: list[str] = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _has_date_series_connector(text: str) -> bool:
    """「从X到Y」「X 到 Y」「X和Y」等连接词表示多个日期事实，禁用 duration-driven。"""
    return any(conn in text for conn in _DATE_SERIES_CONNECTORS)


def _has_day_count_intent(text: str) -> bool:
    """天数意图：半天 / N 天 / N.5 天。"""
    return re.search(r"(?:半|\d+(?:\.\d+)?)\s*天", text) is not None


def _is_duration_driven(*, user_text: str, duration_value, duration_unit,
                        has_discrete_segments: bool) -> bool:
    """只有「单起算日期 + 起算标记 + 天数意图 + 无离散段」才判定为 duration-driven。

    显式范围（两个日期/「到/至」）、离散段、缺天数、非 day 单位、无日期、零/非法时长
    一律不判，保持原有行为。不依赖模型生成的 requested_end_date 判断用户是否说过结束日。
    """
    if not user_text or has_discrete_segments:
        return False
    if duration_unit != DurationUnit.DAY:
        return False
    if not _finite_positive(duration_value if duration_value is not None else 0.0):
        return False
    if not re.search(r"开始|起", user_text):
        return False
    if not _has_day_count_intent(user_text):
        return False
    if _has_date_series_connector(user_text):
        return False
    return len(_extract_date_anchors(user_text)) == 1


def _apply_user_request(draft: LeaveDraftState, request: LeaveDraftRequest,
                        *, user_text: str = "") -> set[str]:
    """把模型输入应用到草稿，返回变更分组（type/date/time/duration/reason）。

    只基于 request.model_fields_set 判断"提供与否"，以区分 omitted（保持旧值）与
    explicit null（清空并失效依赖）。零值按要求保留；未知键/非法值由 Pydantic 原子
    拒绝，本函数只消费通过校验的已知键。日期/时间/时长/类型变更会失效旧权威域。
    """
    provided = set(request.model_fields_set)
    changed: set[str] = set()

    # 判断本轮是否为「从/由某日起（开始）请 N 天」的 duration-driven 请求：用户只给一个
    # 起算日期，结束日由天数/连续自然日或跳休排班规则决定；模型生成的 requested_end_date
    # 不是用户事实。（不依赖模型推算的 end 来判断用户是否说过结束日。）
    eff_duration = request.duration_value if "duration_value" in provided else draft.duration_value
    eff_unit = request.duration_unit if "duration_unit" in provided else draft.duration_unit
    eff_segments = bool(request.requested_date_segments) or bool(draft.requested_date_segments)
    is_duration_driven = _is_duration_driven(
        user_text=user_text,
        duration_value=eff_duration,
        duration_unit=eff_unit,
        has_discrete_segments=eff_segments,
    )

    # 假期类型：explicit null 清空类型/权威/confirmation；未知类型一定 revision。
    if "type_name" in provided:
        raw = request.type_name
        if raw is None:
            if (draft.normalized_type_name is not None or draft.type_code is not None
                    or draft.type_source is not None):
                _clear_authority(draft)
                draft.normalized_type_name = None
                draft.type_code = None
                draft.type_source = None
                draft.raw_type_expression = None
                changed.add("type")
        else:
            raw = str(raw).strip()
            draft.raw_type_expression = raw
            cand = normalize_type_name(raw) if raw else None
            if cand is None:
                # 未知类型：清权威并置 None，且一定标记 changed（revision 递增）。
                _clear_authority(draft)
                draft.normalized_type_name = None
                draft.type_code = None
                draft.type_source = None
                changed.add("type")
                draft.validation_errors.append(f"未知假期类型：{raw}")
            elif cand != draft.normalized_type_name:
                normalize_type(draft, raw)
                changed.add("type")

    # 日期（用户请求层）
    if "requested_start_date" in provided:
        v = request.requested_start_date
        if v is None:
            if draft.requested_start_date is not None:
                draft.requested_start_date = None
                changed.add("date")
        elif v != draft.requested_start_date:
            draft.requested_start_date = v
            changed.add("date")
    if is_duration_driven:
        # duration-driven：结束日由天数/连续自然日或跳休排班规则计算，模型推算的
        # requested_end_date 并非用户事实，一律不写入；若草稿已有旧 end 则清空并标记日期变更。
        if draft.requested_end_date is not None:
            draft.requested_end_date = None
            changed.add("date")
    elif "requested_end_date" in provided:
        v = request.requested_end_date
        if v is None:
            if draft.requested_end_date is not None:
                draft.requested_end_date = None
                changed.add("date")
        elif v != draft.requested_end_date:
            draft.requested_end_date = v
            changed.add("date")
    if "requested_date_segments" in provided:
        v = request.requested_date_segments
        if v is None:
            if draft.requested_date_segments:
                draft.requested_date_segments = []
                changed.add("date")
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            if list(draft.requested_date_segments) != list(v):
                draft.requested_date_segments = list(v)
                changed.add("date")
            if v:
                # 离散段是更具体的用户日期事实：即使模型遗漏或给了不一致的
                # requested_start_date，也确定性把起点设为最早 segment。日期已由 Pydantic
                # 校验为 ISO，min(v) 即最早日期。只写 start，不把 requested_end_date 填成
                # 最大 segment，也不把离散段改成连续范围。起点变化仍走 date 变更，复用现有
                # authority 清除与 revision 递增；空/None 沿用现有清空 segments 行为，不凭空
                # 清除独立 start。
                earliest = min(v)
                if draft.requested_start_date != earliest:
                    draft.requested_start_date = earliest
                    changed.add("date")

    # 时间表达：非法值将被 Pydantic 拒绝；此处对显式清空与有效变化处理。
    if "time_mode" in provided:
        v = request.time_mode
        tm = _to_time_mode(v) if v is not None else None
        if v is None:
            if draft.time_mode is not None:
                draft.time_mode = None
                changed.add("time")
        elif tm is not None and tm != draft.time_mode:
            draft.time_mode = tm
            changed.add("time")
        elif tm is None:
            draft.time_mode = None
            changed.add("time")
            draft.validation_errors.append(f"无法识别的时间表达：{v}")
    if "requested_start_time" in provided:
        v = request.requested_start_time
        if v is None:
            if draft.requested_start_time is not None:
                draft.requested_start_time = None
                changed.add("time")
        elif v != draft.requested_start_time:
            draft.requested_start_time = v
            changed.add("time")
    if "requested_end_time" in provided:
        v = request.requested_end_time
        if v is None:
            if draft.requested_end_time is not None:
                draft.requested_end_time = None
                changed.add("time")
        elif v != draft.requested_end_time:
            draft.requested_end_time = v
            changed.add("time")
    if "requested_hours" in provided:
        v = request.requested_hours
        if v is None:
            if draft.requested_hours is not None:
                draft.requested_hours = None
                changed.add("time")
        elif v != draft.requested_hours:
            draft.requested_hours = v
            changed.add("time")
    if "hour_anchor" in provided:
        v = request.hour_anchor
        if v is None:
            if draft.hour_anchor is not None:
                draft.hour_anchor = None
                changed.add("time")
        elif v != draft.hour_anchor:
            draft.hour_anchor = v
            changed.add("time")

    # 时长（用户请求层；零值保留，不 x or 1）
    if "duration_value" in provided:
        v = request.duration_value
        if v is None:
            if draft.duration_value is not None:
                draft.duration_value = None
                changed.add("duration")
        elif v != draft.duration_value:
            draft.duration_value = v
            changed.add("duration")
    if "duration_unit" in provided:
        v = request.duration_unit
        du = _to_duration_unit(v) if v is not None else None
        if v is None:
            if draft.duration_unit is not None:
                draft.duration_unit = None
                changed.add("duration")
        elif du is not None and du != draft.duration_unit:
            draft.duration_unit = du
            changed.add("duration")
        elif du is None:
            draft.duration_unit = None
            changed.add("duration")
            draft.validation_errors.append(f"无法识别的时长单位：{v}")

    # 理由（需 origin 校验）
    if _apply_reason(draft, request, provided, user_text):
        changed.add("reason")

    # 除 reason 外的交易字段变更都会失效旧权威域。
    if changed - {"reason"}:
        _clear_authority(draft)
        draft.invalidation_reason = None
    # 仅当实际日期输入发生变化时记录该轮原文作为日期表达来源；reason-only/read-only 保留
    # 旧表达，避免每轮用整句覆盖、丢失最初表达。
    if "date" in changed and user_text:
        draft.requested_date_expression = user_text
    return changed


def _provider_error(draft: LeaveDraftState, resp: dict) -> DraftResult:
    code = resp.get("error_type") or "gaia_error"
    message = resp.get("message") or "假期数据暂时无法查询，请稍后再试。"
    return _result(draft, DraftStatus.VALIDATION_FAILED,
                   error_code=code, error_message=message)


_HORIZON_MESSAGE = "排班范围不足，暂时无法确认所需工作日。"


def _fetch_span(request_provider, employee_id: str, start: str, target_end: str):
    """按无重叠、最多 _SCHEDULE_WINDOW_DAYS 日（含首尾）的窗口反复查询 [start, target_end]。

    把所有窗口的原始 data 合并后构造一张 ScheduleDayTable。任一批 provider 返回非成功或
    抛异常即原子失败（沿用现有 error_type/message），绝不把已取到的局部表当成功。
    """
    items = []
    cur = _parse_date(start)
    end_d = _parse_date(target_end)
    while cur <= end_d:
        win_start = _iso(cur)
        win_end = _iso(min(cur + timedelta(days=_SCHEDULE_WINDOW_DAYS - 1), end_d))
        try:
            resp = request_provider.schedule(win_start, win_end, employee_id)
        except Exception:
            return None, "gaia_error", "排班暂时无法查询，请稍后再试。"
        if not resp.get("success"):
            return None, resp.get("error_type") or "gaia_error", (
                resp.get("message") or "排班暂时无法查询，请稍后再试。"
            )
        items.extend(resp.get("data") or [])
        if win_end == target_end:
            break
        cur = _parse_date(win_end) + timedelta(days=1)
    return build_schedule_table(items), None, None


def _fetch_limited_span(request_provider, employee_id: str, start: str, target_end: str):
    """固定必要跨度 [start, target_end]：自然日跨度 >366 直接返回 schedule_horizon_exceeded。"""
    if target_end < start:
        target_end = start
    span = (_parse_date(target_end) - _parse_date(start)).days + 1
    if span > HORIZON_SAFE_LIMIT_DAYS:
        return None, "schedule_horizon_exceeded", _HORIZON_MESSAGE
    return _fetch_span(request_provider, employee_id, start, target_end)


def _count_workdays_until_enough(
    start: str,
    covered_end: date,
    table: ScheduleDayTable,
    needed: int,
) -> tuple[bool, bool, int]:
    """从 start 起按日连续扫描已查询范围，直到达到 needed 个 WORK / 遇 UNKNOWN / 扫到尾。

    返回 (enough, hit_unknown, workdays)。REST 不计数但继续；UNKNOWN 不跳过、立即置
    hit_unknown；达到 needed 即返回 enough=True，不再看更晚的缺行。
    """
    count = 0
    cur = _parse_date(start)
    while cur <= covered_end:
        status = table.day(_iso(cur))
        if status is DayStatus.UNKNOWN:
            return False, True, count
        if status is DayStatus.WORK:
            count += 1
            if count >= needed:
                return True, False, count
        cur = cur + timedelta(days=1)
    return False, False, count


def _fetch_skip_rest_duration(request_provider, employee_id: str, start: str, duration):
    """跳休 + 仅 duration_value：由所需工作日数量动态向后扩窗，最多 366 个自然日。

    每批窗口后统计从 start 起按日连续扫描的 WORK；REST 不计数；遇已查询范围内缺行/UNKNOWN
    立即停止扩展（交给领域规则返回 schedule_unknown）；工作日够了即停止；所需工作日本身
    >366 或 366 日覆盖仍找不够 → schedule_horizon_exceeded（先于余额）。
    """
    needed = int(math.ceil(duration))
    if needed <= 1:
        # 单个工作日：只依赖 start 当日事实，由领域规则判 rest_day / schedule_unknown / 成功。
        return _fetch_span(request_provider, employee_id, start, start)
    if needed > HORIZON_SAFE_LIMIT_DAYS:
        # 所需工作日本身超过 366 个自然日：直接 horizon，绝不变 schedule_unknown。
        return None, "schedule_horizon_exceeded", _HORIZON_MESSAGE
    items = []
    win_start_date = _parse_date(start)
    max_end = _parse_date(start) + timedelta(days=HORIZON_SAFE_LIMIT_DAYS - 1)
    while True:
        win_end_date = min(
            win_start_date + timedelta(days=_SCHEDULE_WINDOW_DAYS - 1), max_end
        )
        win_start = _iso(win_start_date)
        win_end = _iso(win_end_date)
        try:
            resp = request_provider.schedule(win_start, win_end, employee_id)
        except Exception:
            return None, "gaia_error", "排班暂时无法查询，请稍后再试。"
        if not resp.get("success"):
            return None, resp.get("error_type") or "gaia_error", (
                resp.get("message") or "排班暂时无法查询，请稍后再试。"
            )
        items.extend(resp.get("data") or [])
        table = build_schedule_table(items)
        enough, hit_unknown, _ = _count_workdays_until_enough(start, win_end_date, table, needed)
        if enough:
            break
        if hit_unknown:
            break
        if win_end_date >= max_end:
            # 已覆盖完整 366 日仍找不够所需工作日，返回 horizon（先于余额）。
            return None, "schedule_horizon_exceeded", _HORIZON_MESSAGE
        win_start_date = win_end_date + timedelta(days=1)
    return table, None, None


def _schedule_table_for(request_provider, employee_id: str, draft: LeaveDraftState):
    """按领域所需日期/工作日驱动扩窗查询排班（30 日无重叠窗口，最多 366 个自然日）。

    返回 (table, error_code, error_message)。跳休 + 仅 duration_value 由所需工作日数量
    动态向后扩窗；显式 requested_end_date / 离散段 / 连续自然日按必要自然日分批；小时/半天/
    单日只查所需日。整个请求从 requested_start_date 起最多覆盖 366 个自然日。
    """
    start = draft.requested_start_date
    if not start:
        return None, None, ""
    continuous = is_continuous_leave(draft.normalized_type_name or "")
    mode = draft.time_mode
    intent = draft.duration_value
    segs = draft.requested_date_segments or []
    end = draft.requested_end_date

    # 小时 / 半天：只查所需日（requested_start_date 单日）。
    if mode in (TimeMode.EXPLICIT_RANGE, TimeMode.EXPLICIT_HOURS,
                TimeMode.FIRST_HALF, TimeMode.SECOND_HALF):
        return _fetch_span(request_provider, employee_id, start, start)

    # 全天范畴：离散段 / 显式范围 / 时长。
    distinct_segs = sorted(set(segs)) if segs else []
    if len(distinct_segs) > 1:
        target_end = max(distinct_segs)
        return _fetch_limited_span(request_provider, employee_id, start, target_end)
    if end and end != start:
        return _fetch_limited_span(request_provider, employee_id, start, end)

    # 时长（无 requested_end_date、无多段）或单日全天。
    if intent is not None and not _finite_positive(intent):
        # 零/负/非有限：仍由现有 invalid_duration 优先；只取最小所需窗口，不抛异常、不改 horizon。
        return _fetch_span(request_provider, employee_id, start, start)

    duration = intent if intent is not None else 1.0
    if continuous:
        target_end = _add_days(start, int(math.ceil(duration)) - 1)
        return _fetch_limited_span(request_provider, employee_id, start, target_end)

    # 跳休 + 仅 duration_value：由所需工作日数量动态向后扩窗。
    return _fetch_skip_rest_duration(request_provider, employee_id, start, duration)


def advance_leave_draft(
    draft: LeaveDraftState,
    request: LeaveDraftRequest,
    *,
    provider,
    employee_id: str,
    user_text: str = "",
) -> DraftResult:
    """把模型输入应用到草稿并推进状态机（单一草稿领域服务，供 save_leave_draft 工具）。

    provider/employee_id 来自 request-bound HR context。排班/权限/性别/余额由本函数
    按 WP-02 §15 顺序读取 provider；权限/性别在排班与余额查询前实际拒绝。
    仅 reason 变更且已有有效权威时长时保留权威/验证证据、不重查排班/余额；失败/终态
    不得因改 reason 升级为可确认；read-only 与失败态保留结构化错误类别。
    """
    if draft.status in (DraftStatus.CONFIRMED, DraftStatus.TERMINAL):
        # 终态草稿不可再修改：保持当前快照终态，不重查 Gaia、不改 id/revision/authority，
        # 防止任何日期更新把已确认/终态的草稿重开。
        missing = compute_missing_fields(draft)
        return DraftResult(
            state=draft, status=draft.status, missing=missing,
            error_code=draft.status_error_code, error_message=draft.status_error_message,
        )

    if _has_type_conflict(user_text):
        draft.validation_errors.append("一次申请只能包含一个假期类型，请分开提交。")
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="type_conflict",
                       error_message="一次申请只能包含一个假期类型，请分开提交。")

    changed = _apply_user_request(draft, request, user_text=user_text)
    if not changed:
        # 只读 / 无有效变化：不 revision、不重算；保留已有错误类别（若有）。
        missing = compute_missing_fields(draft)
        return DraftResult(
            state=draft, status=draft.status, missing=missing,
            error_code=draft.status_error_code, error_message=draft.status_error_message,
        )
    draft.revision += 1

    if changed == {"reason"} and draft.authoritative_duration_value is not None:
        # 仅改理由：保留已有权威与验证证据，只失效 confirmation，状态不变。
        # read/collecting 保持可继续；失败/终态不升级。
        draft.last_displayed_invocation_id = None
        if draft.status is DraftStatus.READY_FOR_CONFIRMATION:
            draft.status = DraftStatus.READY_FOR_CONFIRMATION
        return DraftResult(
            state=draft, status=draft.status, missing=compute_missing_fields(draft),
            error_code=draft.status_error_code, error_message=draft.status_error_message,
        )

    missing = compute_missing_fields(draft)
    if not missing.is_empty():
        draft.status = DraftStatus.COLLECTING
        # 缺字段回到 collecting：清掉上一轮残留的结构化错误，避免过期错误出现在已补齐的
        # collecting 快照里。
        draft.status_error_code = None
        draft.status_error_message = ""
        draft.last_displayed_invocation_id = None
        return DraftResult(state=draft, status=DraftStatus.COLLECTING, missing=missing)

    # 槽位齐备：权限→性别（在排班/余额前实际拒绝）。
    perms = provider.leave_permissions(employee_id)
    if not perms.get("success"):
        return _provider_error(draft, perms)
    allowed_types = [p["leave_type"] for p in perms.get("data") or []]
    if draft.type_code is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="no_permission",
                       error_message="未知假期类型，无法申请。")
    if draft.normalized_type_name not in allowed_types:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="no_permission",
                       error_message="您暂无权限申请该类型假期，请核对后重试或咨询 HR。")

    sex = None
    if draft.normalized_type_name and draft.normalized_type_name in LEAVE_GENDER_MAP:
        info = provider.employee_info(employee_id)
        if not info.get("success"):
            return _provider_error(draft, info)
        sex = info["data"].get("sex")
        if sex is None:
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="gender_unknown",
                           error_message="该假期需要确认员工性别。")
        if LEAVE_GENDER_MAP[draft.normalized_type_name] != sex:
            label = "男性" if LEAVE_GENDER_MAP[draft.normalized_type_name] == "M" else "女性"
            return _result(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="gender_mismatch",
                           error_message=f"该假期仅限{label}员工申请。")

    table, table_err, table_msg = _schedule_table_for(provider, employee_id, draft)
    if table_err:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code=table_err, error_message=table_msg or "排班暂时无法查询，请稍后再试。")
    if table is None:
        return _result(draft, DraftStatus.VALIDATION_FAILED,
                       error_code="schedule_unknown",
                       error_message="排班证据不足，暂无法办理。")

    auth = compute_authoritative(draft, table=table)
    if auth.status is not DraftStatus.READY_FOR_VALIDATION:
        return auth

    balance = provider.leave_balance(draft.normalized_type_name, employee_id)
    if not balance.get("success"):
        return _provider_error(draft, balance)
    return validate_permission_gender_balance(
        draft,
        allowed_types=allowed_types,
        sex=sex,
        balance=balance.get("data") or [],
    )
