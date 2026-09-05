"""考勤量化计算工具：模型只提取结构，单位/边界/豁免/扣款由确定性规则完成。"""

from packages.hr_domain.schemas.attendance import (
    AttendanceInput,
    AttendanceKind,
    AttendanceRecord,
    MonthlyExemptContext,
)
from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.rules.attendance import (
    calculate_attendance,
    parse_duration_minutes,
)


def _parse_kind(value) -> AttendanceKind | None:
    """late/迟到 → LATE；early_leave/早退 → EARLY_LEAVE。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"late", "迟到"}:
        return AttendanceKind.LATE
    if normalized in {"early_leave", "early", "早退"}:
        return AttendanceKind.EARLY_LEAVE
    return None


def _as_exempt_count(value):
    """解析一侧免扣次数：None→未知；非负整数→已知；负数/非法→抛 ValueError(fail closed)。

    绝不把「未知/非法」静默转成 0——否则会把未提供的一侧当作已有 0 次而错误放行。
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid monthly exempt count")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("invalid monthly exempt count")
        normalized = int(value)
    else:
        normalized = value
    if normalized < 0:
        raise ValueError("invalid monthly exempt count")
    return normalized


def _monthly_entry(monthly_exempt: dict | None) -> MonthlyExemptContext | None:
    if not isinstance(monthly_exempt, dict):
        return None
    late = _as_exempt_count(monthly_exempt.get("late_prior_exempt"))
    early = _as_exempt_count(monthly_exempt.get("early_leave_prior_exempt"))
    if late is None and early is None:
        return None
    return MonthlyExemptContext(late_prior_exempt=late, early_leave_prior_exempt=early)


def attendance_calculation(records: list, monthly_exempt: dict | None = None,
                           tool_context=None) -> dict:
    """按确定性规则计算迟到/早退金额与旷工天数。

    Args:
        records: 异常记录列表，每项含 {"kind": "late"|"early_leave", "duration": "20分钟"|"1小时"|...}
        monthly_exempt: 可选，本月已用免扣次数，如 {"late_prior_exempt": 2}；
            缺省时对 10 分钟内记录会返回 need_more_information（不猜第一次/第三次）。
    """
    if not isinstance(records, list) or not records:
        return _err("insufficient_attendance_duration", "请提供迟到/早退时长。")

    parsed_records: list[AttendanceRecord] = []
    for idx, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            return _err("insufficient_attendance_duration", "异常记录格式无效。")
        kind = _parse_kind(item.get("kind"))
        if kind is None:
            return _err("insufficient_attendance_duration", "无法识别迟到还是早退。")
        minutes = parse_duration_minutes(item.get("duration"))
        if minutes is None:
            return _err("insufficient_attendance_duration",
                        "请提供明确的迟到/早退时长（如 10 分钟、半小时、1 小时）。")
        parsed_records.append(AttendanceRecord(
            kind=kind, duration_minutes=minutes,
            source_expression=str(item.get("duration", "")), sequence=idx,
        ))

    try:
        exempt_context = _monthly_entry(monthly_exempt)
    except ValueError:
        # 月度免扣次数为负数/非法：fail closed，不当作 0 放行。
        return _err("invalid_monthly_exempt_context", "请提供有效的本月免扣次数。")

    result = calculate_attendance(AttendanceInput(
        records=parsed_records,
        exempt_context=exempt_context,
    ))

    if result.unresolved_context:
        return _err(
            "need_more_information",
            "需要确认本月此前已有几次 10 分钟内迟到/早退免扣记录。",
        )

    serialized = {
        "records": [
            {
                "sequence": rec.sequence,
                "kind": "late" if rec.kind is AttendanceKind.LATE else "early_leave",
                "original_minutes": rec.original_minutes,
                "chargeable_bucket": rec.chargeable_bucket,
                "deduction": rec.deduction,
                "absence_days": rec.absence_days,
                "exemption_applied": rec.exemption_applied,
                "is_severe": rec.is_severe,
            }
            for rec in result.records
        ],
        "total_deduction": result.total_deduction,
        "total_absence_days": result.total_absence_days,
    }
    return ok(serialized)


def _err(error_type: str, message: str) -> dict:
    return {"success": False, "error_type": error_type, "message": message}
