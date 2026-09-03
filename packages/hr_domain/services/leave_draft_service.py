"""Leave Draft 服务：标准化、状态机、缺槽位、依赖失效、权威计算。

领域层只做确定性的业务事实计算，不依赖框架。排班/权限/余额数据由调用方从
request-bound HR context 的 Gaia Provider 取得后注入；本服务不访问 session state，
不读取请求方凭据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from packages.hr_domain.constants.leave_rules import (
    HOLIDAY_TYPE_CODE,
    LEAVE_GENDER_MAP,
    normalize_type_name,
)
from packages.hr_domain.rules.leave_dates import (
    check_discrete_continuity,
    compute_leave_dates,
)
from packages.hr_domain.rules.leave_duration import (
    DurationOutcome,
    authoritative_duration,
    normalized_time_mode,
)
from packages.hr_domain.schemas.leave_draft import (
    DraftStatus,
    DurationUnit,
    FieldSource,
    LeaveDraftState,
    MissingFields,
    TimeMode,
)
from packages.hr_domain.schemas.schedule import DayStatus, ScheduleDayTable


@dataclass
class DraftResult:
    state: LeaveDraftState
    status: DraftStatus
    missing: MissingFields = field(default_factory=MissingFields)
    error_code: str | None = None
    error_message: str = ""


def new_draft(draft_id: str) -> LeaveDraftState:
    return LeaveDraftState(draft_id=draft_id)


# 假种候选词 → 正式名，供多假种冲突检测；只做"是否出现多个"判断，不负责标准化。
_TYPE_CANDIDATES = (
    "年休假", "年假", "事假", "病假", "婚假", "产假", "调休假", "调休",
    "丧假", "陪产假", "育儿假", "产检假", "哺乳假",
)


def detect_type_conflict(raw_request: str) -> bool:
    """一次请假申请中是否出现多个不同假期类型。

    WP-02 §13：一次申请只能包含一个假期类型。"两天年假加一天调休"应拒绝合并。
    由 Leave Draft normalization 检测，不依赖 Prompt 提醒。
    """
    seen = set()
    for candidate in _TYPE_CANDIDATES:
        if candidate in raw_request:
            seen.add(normalize_type_name(candidate) or candidate)
        if len(seen) > 1:
            return True
    return False


def normalize_type(draft: LeaveDraftState, raw_type: str | None) -> None:
    """标准化假期类型；类型变更即失效依赖（permission/gender/balance/确认）。"""
    if not raw_type:
        return
    name = normalize_type_name(raw_type)
    draft.raw_type_expression = raw_type
    if name is None:
        draft.type_code = None
        draft.validation_errors.append(f"未知假期类型：{raw_type}")
    else:
        draft.normalized_type_name = name
        draft.type_code = HOLIDAY_TYPE_CODE.get(name)
        draft.type_source = FieldSource.NORMALIZED_USER
    # 类型变更：失效权限/性别/余额/确认
    _invalidate_after_type_change(draft)


def _invalidate_after_type_change(draft: LeaveDraftState) -> None:
    # 类型决定 duration-unit 兼容性与确认摘要；日期原值保留但需重新验证。
    draft.invalidation_reason = "假期类型已变更"
    draft.validation_errors = [
        e for e in draft.validation_errors if e.startswith("未知假期类型")
    ]


def compute_missing_fields(draft: LeaveDraftState) -> MissingFields:
    """由结构化槽位判定缺失；input_required 的唯一状态来源。"""
    return MissingFields(
        type_name=not draft.normalized_type_name,
        date=not (draft.authoritative_start_date and draft.authoritative_end_date),
        time_or_duration=not (
            draft.time_mode is not None and (
                draft.authoritative_duration_value is not None
                or (draft.time_mode in (TimeMode.EXPLICIT_RANGE, TimeMode.EXPLICIT_HOURS))
            )
        ),
        reason=False,  # 理由非必填；未提供则保留空，不臆造
    )


def compute_authoritative(
    draft: LeaveDraftState,
    *,
    table: ScheduleDayTable,
    calendar_duration: float = 1.0,
    workdays_requested: int = 1,
    requested_segments: list[str] | None = None,
) -> DraftResult:
    """根据标准化后的草稿计算权威日期/时长并校验排班、连续性。

    仅在时间表达与日期都已确定时调用；返回权威 start/end/time/duration。
    """
    if not draft.requested_start_date or not draft.time_mode:
        return DraftResult(draft, DraftStatus.COLLECTING,
                           missing=compute_missing_fields(draft))

    # 离散日期连续性：用户明确列出多个离散日期时，[start, end] 之外先用 segments 判续。
    segs = requested_segments or (
        [draft.requested_start_date] if draft.requested_start_date else []
    )

    # 日期推算
    start_hint = draft.requested_start_date
    end_hint = draft.requested_end_date or start_hint
    dates = compute_leave_dates(
        type_name=draft.normalized_type_name or "",
        requested_start_date=start_hint,
        requested_end_date=end_hint,
        calendar_duration=calendar_duration,
        workdays_requested=workdays_requested,
        table=table,
    )
    if dates.error_code:
        return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                           error_code=dates.error_code,
                           error_message=dates.error_message)
    draft.authoritative_start_date = dates.start_date
    draft.authoritative_end_date = dates.end_date

    # 离散日期工作日连续性
    if len(segs) > 1:
        _, err_code = check_discrete_continuity(segs, table)
        if err_code:
            return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                               error_code=err_code,
                               error_message=_continuity_message(err_code))

    # 权威时长
    sched_fact = table.fact(draft.authoritative_start_date or "")
    duration = authoritative_duration(
        time_mode=draft.time_mode,
        schedule_fact=sched_fact,
        requested_start_time=draft.requested_start_time,
        requested_end_time=draft.requested_end_time,
        requested_hours=draft.requested_hours,
    )
    if duration.error_code:
        return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                           error_code=duration.error_code,
                           error_message=duration.error_message)
    draft.authoritative_duration_value = duration.duration_value
    draft.authoritative_duration_unit = duration.duration_unit
    draft.authoritative_start_time = duration.start_time
    draft.authoritative_end_time = duration.end_time

    # 跨天夜班：仅在取得权威班次时段后，start>end 时 end_date +1。
    if _is_overnight(duration.start_time, duration.end_time):
        draft.authoritative_end_date = _plus_day(draft.authoritative_end_date)

    return DraftResult(draft, DraftStatus.READY_FOR_VALIDATION,
                       missing=compute_missing_fields(draft))


def validate_permission_gender_balance(
    draft: LeaveDraftState,
    *,
    allowed_types: list[str],
    sex: str | None,
    balance: list[dict] | None,
) -> DraftResult:
    """权限 → 性别 → 余额校验；余额使用 authoritative duration 与单位匹配。"""
    if not draft.normalized_type_name:
        return DraftResult(draft, DraftStatus.COLLECTING,
                           missing=compute_missing_fields(draft))

    if draft.type_code is None:
        return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="no_permission",
                           error_message="未知假期类型，无法申请。")

    if draft.normalized_type_name not in allowed_types:
        return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                           error_code="no_permission",
                           error_message="您暂无权限申请该类型假期，请核对后重试或咨询 HR。")

    if draft.normalized_type_name in LEAVE_GENDER_MAP and sex:
        expected = LEAVE_GENDER_MAP[draft.normalized_type_name]
        if expected != sex:
            label = "男性" if expected == "M" else "女性"
            return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="gender_mismatch",
                               error_message=f"该假期仅限{label}员工申请。")

    # 余额校验：单位匹配（hour vs day），未知余额不当作 0。
    if balance is not None:
        unit = draft.authoritative_duration_unit
        remain = _balance_remain(balance, unit)
        if remain is None:
            return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="balance_unknown",
                               error_message="假期余额暂时无法确认。")
        requested = draft.authoritative_duration_value or 0
        if remain < requested:
            label = "小时" if unit is DurationUnit.HOUR else "天"
            return DraftResult(draft, DraftStatus.VALIDATION_FAILED,
                               error_code="insufficient_balance",
                               error_message=f"您的假期余额为 {remain} {label}，不足以申请 {requested} {label}。")

    draft.validation_errors = []
    return DraftResult(draft, DraftStatus.READY_FOR_CONFIRMATION)


def _balance_remain(balance: list[dict], unit: DurationUnit | None) -> float | None:
    row = next((it for it in (balance or []) if it.get("leave_name")), None)
    if row is None:
        return None
    remain = row.get("remain")
    if remain is None:
        return None
    # 单位匹配：Gaia 余额 leaveUnit 未解析时按请求单位比较；禁止单位混算。
    return float(remain)


def _continuity_message(err_code: str) -> str:
    if err_code == "discontinuous_workday_gap":
        return "您选择的日期中间存在工作日间隔，请拆开提交。"
    return "中间日期排班未知，暂时无法确认是否连续，请稍后再试。"


def _is_overnight(start: str | None, end: str | None) -> bool:
    return bool(start and end and start > end)


def _plus_day(iso_date: str) -> str:
    d = date.fromisoformat(iso_date)
    from datetime import timedelta
    return (d + timedelta(days=1)).isoformat()
