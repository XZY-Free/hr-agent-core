"""时长权威计算。

模型提供的 leave_days/hours 只是用户意图解释，不是最终事实。权威时长由
领域规则基于排班事实计算；hour/day 单位不混算，无单位换算证据时不硬转
（本轮禁 "8 小时=1 天"）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from packages.hr_domain.schemas.leave_draft import DurationUnit, TimeMode
from packages.hr_domain.schemas.schedule import ScheduleFact

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# 连续自然日遇休息日时的 canonical calendar-day time（领域常量，模型无权决定）。
CALENDAR_DAY_START = "08:00"
CALENDAR_DAY_END = "18:00"


@dataclass(frozen=True)
class DurationOutcome:
    duration_value: float | None
    duration_unit: DurationUnit | None
    start_time: str | None
    end_time: str | None
    error_code: str | None = None
    error_message: str = ""


def _fmt(value: float) -> str:
    return f"{value:02.0f}" if float(value).is_integer() else f"{value:05.1f}"


def authoritative_duration(
    *,
    time_mode: TimeMode,
    schedule_fact: ScheduleFact | None,
    requested_start_time: str | None,
    requested_end_time: str | None,
    requested_hours: float | None,
) -> DurationOutcome:
    """按排班事实计算权威时段与时长。

    返回的 start/end 是权威班次时段；连续自然日遇休息日无班次时用
    CALENDAR_DAY_START/END（来源 rule，不伪造为排班时间）。
    """
    if time_mode == TimeMode.FULL_DAY:
        if schedule_fact is not None and schedule_fact.start_time:
            start = schedule_fact.start_time
            end = schedule_fact.end_time or CALENDAR_DAY_END
        else:
            # 连续自然日遇休息日 / 无明确班次：canonical calendar-day time
            start, end = CALENDAR_DAY_START, CALENDAR_DAY_END
        return DurationOutcome(1.0, DurationUnit.DAY, start, end)

    if time_mode in (TimeMode.FIRST_HALF, TimeMode.SECOND_HALF):
        if schedule_fact is None or not schedule_fact.start_time:
            return DurationOutcome(
                None, None, None, None,
                error_code="schedule_detail_insufficient",
                error_message="当前排班未提供半天边界，暂时无法确定半天排班时段。",
            )
        first_half_end, second_half_start = schedule_fact.half_day_boundaries
        if time_mode is TimeMode.FIRST_HALF:
            if not first_half_end:
                return DurationOutcome(
                    None, None, None, None,
                    error_code="schedule_detail_insufficient",
                    error_message="当前排班未提供半天边界，暂时无法确定半天排班时段。",
                )
            start = schedule_fact.start_time
            end = first_half_end
        else:  # SECOND_HALF
            if not second_half_start:
                return DurationOutcome(
                    None, None, None, None,
                    error_code="schedule_detail_insufficient",
                    error_message="当前排班未提供半天边界，暂时无法确定半天排班时段。",
                )
            start = second_half_start
            end = schedule_fact.end_time or CALENDAR_DAY_END
        # 既有业务语义：0.5 天按半天计
        return DurationOutcome(0.5, DurationUnit.DAY, start, end)

    if time_mode is TimeMode.EXPLICIT_RANGE:
        # 用户显式给 start/end：权威时段即用户时段；时长按小时差计（不硬转 0.5 天）。
        hours = _range_hours(requested_start_time, requested_end_time)
        return DurationOutcome(
            hours,
            DurationUnit.HOUR,
            requested_start_time,
            requested_end_time,
            error_code=None if hours is not None else "invalid_time_range",
            error_message="" if hours is not None else "时间范围无效。",
        )

    if time_mode is TimeMode.EXPLICIT_HOURS:
        # 明确 N 小时：保持 hour 单位，不强制换 0.5 天。
        if requested_hours is None or not _finite_positive(requested_hours):
            return DurationOutcome(
                None, None, None, None,
                error_code="invalid_hours",
                error_message="小时数必须大于 0 且为有限数值。",
            )
        return DurationOutcome(
            requested_hours, DurationUnit.HOUR, requested_start_time, requested_end_time,
        )

    return DurationOutcome(
        None, None, None, None,
        error_code="invalid_time_mode", error_message="无法确定时间表达。",
    )


def normalized_time_mode(
    *,
    full_day: bool = False,
    first_half: bool = False,
    second_half: bool = False,
    explicit_range: bool = False,
    explicit_hours: bool = False,
) -> TimeMode:
    """把用户表达的半天意图标准化为单一 TimeMode。

    缺省 0.5 天（bare half-day）→ FIRST_HALF（领域规则默认，不写进 Prompt）。
    """
    if full_day:
        return TimeMode.FULL_DAY
    if second_half:
        return TimeMode.SECOND_HALF
    if first_half:
        return TimeMode.FIRST_HALF
    if explicit_hours:
        return TimeMode.EXPLICIT_HOURS
    if explicit_range:
        return TimeMode.EXPLICIT_RANGE
    # bare 0.5 天未明确上/下午：默认第一半天
    return TimeMode.FIRST_HALF


def duration_day_value(duration_value: float, duration_unit: DurationUnit) -> float:
    """余额比较用的归一化参考：天单位原值；小时单位仅用于小时余额比较。

    注意：不在这里做"8 小时=1 天"换算——无规则证据时绝不硬转。
    """
    return float(duration_value) if duration_unit is DurationUnit.DAY else float(duration_value)


def _range_hours(start: str | None, end: str | None) -> float | None:
    """start/end HH:mm 差（小时）。跨天（start>end）按次日计；非法时间返回 None。"""
    if not _valid_time(start) or not _valid_time(end):
        return None
    sh, sm = start.split(":")
    eh, em = end.split(":")
    start_min = int(sh) * 60 + int(sm)
    end_min = int(eh) * 60 + int(em)
    if end_min < start_min:
        end_min += 24 * 60
    return (end_min - start_min) / 60.0


def _valid_time(value: str | None) -> bool:
    return bool(value) and _TIME_RE.match(value) is not None


def _finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0
