"""请假日期与排班推算 (规则核心，三态/连续-跳休/366 上限)。

数据源：旧工作流 §3.7 原文，但删除 `>27 天 → shrink_workday` 技术限制，并把排班
从二态改为三态（WORK / REST / UNKNOWN）。未知排班一律不得当作工作日。

- 连续自然日：end = start + (calendar_duration - 1)，包含休息日，不因首日 REST 拒绝。
- 跳休：从权威起算日沿已知排班数满 N 个工作日；REST/UNKNOWN 不计工作日；排班证据
  不足返回 schedule_horizon_exceeded，绝不用未知日期凑数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from packages.hr_domain.constants.leave_rules import SKIP_RESTDAY_MAP
from packages.hr_domain.schemas.schedule import DayStatus, ScheduleDayTable

HORIZON_SAFE_LIMIT_DAYS = 366


@dataclass(frozen=True)
class DateOutcome:
    start_date: str
    end_date: str
    error_code: str | None = None
    error_message: str = ""


def _parse_date(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def _iso(d: date) -> str:
    return d.isoformat()


def is_continuous_leave(type_name: str) -> bool:
    """连续自然日类（含休息日）由 SKIP_RESTDAY_MAP 决定；不在表内默认连续。"""
    return SKIP_RESTDAY_MAP.get(type_name, True)


def calendar_end(start_date: str, calendar_days: float) -> str:
    """连续自然日：end = start + ceil(days) - 1。任何天数一律按此规则，无 27 天分支。"""
    n = max(0, int(_ceil_days(calendar_days)))
    start = _parse_date(start_date)
    return _iso(start + timedelta(days=n - 1))


def _ceil_days(days: float) -> int:
    import math
    return math.ceil(days)


def next_known_workday(start_date: str, table: ScheduleDayTable) -> str | None:
    """从 start 起找第一个明确 WORK 的日期（含当日）。找不到或中途遇 UNKNOWN 返回 None。

    UNKNOWN/REST 不作为起算日；WP-02：UNKNOWN 在需要的路径上不得被跳过，遇 UNKNOWN
    即 fail-closed。若整个 366 天窗口都无 WORK 或中途遇 UNKNOWN，返回 None。
    """
    cur = _parse_date(start_date)
    for _ in range(HORIZON_SAFE_LIMIT_DAYS):
        status = table.day(_iso(cur))
        if status is DayStatus.WORK:
            return _iso(cur)
        if status is DayStatus.UNKNOWN:
            # UNKNOWN 不能当工作日，也不能当已知休息日；不得跳过寻找更晚 WORK。
            return None
        cur = cur + timedelta(days=1)
    return None


def compute_skip_rest_end(
    effective_start: str,
    workdays_requested: int,
    table: ScheduleDayTable,
    *,
    max_window_days: int = HORIZON_SAFE_LIMIT_DAYS,
) -> DateOutcome:
    """跳休：从 effective_start 沿排班累计 N 个明确 WORK 日。

    - 已知 REST 不计工作天数但继续向后搜；
    - UNKNOWN 在需要路径上不得跳过，遇 UNKNOWN 即 fail-closed（schedule_unknown）；
    - 找到 N 个 WORK 即返回其日期为 end；
    - 超过安全上限仍未找够 → schedule_horizon_exceeded；
    - 排班表没有任何 WORK 证据 → schedule_unknown。
    """
    if workdays_requested <= 0:
        return DateOutcome(effective_start, effective_start,
                           error_code="invalid_days",
                           error_message="请假天数必须大于 0。")
    if not table.known_workdays():
        return DateOutcome(effective_start, effective_start,
                           error_code="schedule_unknown",
                           error_message="排班证据不足，无法确认工作日。")
    cur = _parse_date(effective_start)
    count = 0
    end = effective_start
    for _ in range(max_window_days):
        status = table.day(_iso(cur))
        if status is DayStatus.UNKNOWN:
            return DateOutcome(effective_start, end,
                               error_code="schedule_unknown",
                               error_message="排班在需要日期上未知，无法确认工作日。")
        if status is DayStatus.WORK:
            count += 1
            end = _iso(cur)
            if count >= workdays_requested:
                return DateOutcome(effective_start, end)
        cur = cur + timedelta(days=1)
    return DateOutcome(effective_start, end,
                       error_code="schedule_horizon_exceeded",
                       error_message="排班范围不足，暂时无法确认所需工作日。")


def compute_leave_dates(
    *,
    type_name: str,
    requested_start_date: str,
    requested_end_date: str,
    calendar_duration: float,
    workdays_requested: int,
    table: ScheduleDayTable,
) -> DateOutcome:
    """统一日期推算入口。

    连续自然日：start=requested，end=calendar_end。
    跳休：
      - 若 requested_start 是明确 REST：authoritative_start 为之后第一个已知 WORK；
        单日请求（workdays=1）且首日即 REST → 仍保留 requested_start 并返回 rest_day 标记。
      - 否则 authoritative_start = 首个明确 WORK 起算日。
    """
    continuous = is_continuous_leave(type_name)
    if continuous:
        return DateOutcome(
            start_date=requested_start_date,
            end_date=calendar_end(requested_start_date, calendar_duration),
        )

    start_status = table.day(requested_start_date)
    if start_status is DayStatus.REST and workdays_requested <= 1:
        # 单日跳休落在明确休息日：不改期、不移动到周一，返回 rest_day。
        return DateOutcome(
            start_date=requested_start_date,
            end_date=requested_start_date,
            error_code="rest_day",
            error_message="该日期是正常休息日，不需要请假。",
        )
    if start_status is DayStatus.UNKNOWN:
        # 未知排班：不当作工作日，须有排班证据才能推算。
        if not table.known_workdays():
            return DateOutcome(
                requested_start_date, requested_start_date,
                error_code="schedule_unknown",
                error_message="排班证据不足，暂时无法确认工作日。",
            )
    effective_start = next_known_workday(requested_start_date, table)
    if effective_start is None:
        return DateOutcome(
            requested_start_date, requested_start_date,
            error_code="schedule_unknown",
            error_message="排班证据不足，暂时无法确认工作日。",
        )
    return compute_skip_rest_end(effective_start, workdays_requested, table)


def check_discrete_continuity(
    requested_segments: list[str],
    table: ScheduleDayTable,
) -> tuple[bool, str | None]:
    """离散日期连续性：segments 之间若有明确 WORK → 不连续；UNKNOWN → 不确定。

    返回 (is_continuous, error_code)。error_code ∈ {
      None（连续）, discontinuous_workday_gap, schedule_unknown_for_continuity
    }
    """
    if len(requested_segments) <= 1:
        return True, None
    ordered = sorted(requested_segments)
    for lo, hi in zip(ordered, ordered[1:]):
        gap_start = _parse_date(lo) + timedelta(days=1)
        gap_end = _parse_date(hi)
        cur = gap_start
        while cur < gap_end:
            status = table.day(_iso(cur))
            if status is DayStatus.WORK:
                return False, "discontinuous_workday_gap"
            if status is DayStatus.UNKNOWN:
                # 中间出现未知排班：不得武断判连续。
                return False, "schedule_unknown_for_continuity"
            cur = cur + timedelta(days=1)
    return True, None
