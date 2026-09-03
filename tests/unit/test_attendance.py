"""WP-04 考勤量化计算确定性规则测试。"""

import pytest

from packages.hr_domain.schemas.attendance import (
    AttendanceInput,
    AttendanceKind,
    AttendanceRecord,
    MonthlyExemptContext,
)
from packages.hr_domain.rules.attendance import (
    calculate_attendance,
    parse_duration_minutes,
)


def _late(m, seq=1):
    return AttendanceRecord(kind=AttendanceKind.LATE, duration_minutes=m, sequence=seq)


def _early(m, seq=1):
    return AttendanceRecord(kind=AttendanceKind.EARLY_LEAVE, duration_minutes=m, sequence=seq)


def _ctx(**kw):
    kw.setdefault("late_prior_exempt", 2)
    kw.setdefault("early_leave_prior_exempt", 2)
    return MonthlyExemptContext(**kw)


# ---------- 单条一般异常（<60 分钟） ----------

@pytest.mark.parametrize("minutes,bucket,deduction", [
    (11, 20, 40.0), (19, 20, 40.0), (20, 20, 40.0), (21, 30, 60.0),
    (49, 50, 100.0), (50, 50, 100.0), (51, 60, 120.0), (59, 60, 120.0),
])
def test_general_late_buckets(minutes, bucket, deduction):
    r = calculate_attendance(AttendanceInput(
        records=[_late(minutes)], exempt_context=_ctx()))
    rec = r.records[0]
    assert rec.chargeable_bucket == bucket
    assert rec.deduction == deduction
    assert rec.is_severe is False
    assert rec.absence_days == 0.0


def test_51_59_is_not_severe():
    # 51~59 分钟取整到 60 桶，但仍是"未达 60 一般异常"，不判严重迟到。
    rec = calculate_attendance(AttendanceInput(
        records=[_late(59)], exempt_context=_ctx())).records[0]
    assert rec.chargeable_bucket == 60
    assert rec.is_severe is False
    assert rec.absence_days == 0.0
    assert rec.deduction == 120.0


# ---------- 严重迟到 / 早退 ----------

@pytest.mark.parametrize("minutes,absence_days", [
    (60, 0.5), (61, 0.5), (239, 0.5), (240, 1.0), (250, 1.0),
])
def test_severe_absence_days(minutes, absence_days):
    rec = calculate_attendance(AttendanceInput(records=[_late(minutes)])).records[0]
    assert rec.absence_days == absence_days
    assert rec.is_severe is True
    assert rec.deduction == 0.0  # 严重记录不再产生金额


# ---------- 10 分钟（含）以内月度豁免 ----------

def test_prior_0_8min_exempt():
    rec = calculate_attendance(AttendanceInput(
        records=[_late(8)], exempt_context=_ctx(late_prior_exempt=0))).records[0]
    assert rec.exemption_applied is True
    assert rec.deduction == 0.0


def test_prior_1_8min_exempt():
    rec = calculate_attendance(AttendanceInput(
        records=[_late(8)], exempt_context=_ctx(late_prior_exempt=1))).records[0]
    assert rec.exemption_applied is True
    assert rec.deduction == 0.0


def test_prior_2_8min_deduct():
    rec = calculate_attendance(AttendanceInput(
        records=[_late(8)], exempt_context=_ctx(late_prior_exempt=2))).records[0]
    assert rec.exemption_applied is False
    assert rec.deduction == 20.0


def test_missing_prior_8min_needs_context():
    # 未提供月度上下文，不猜第一次或第三次 → 标记需追问。
    r = calculate_attendance(AttendanceInput(records=[_late(8)]))
    rec = r.records[0]
    assert rec.needed_context is True
    assert r.unresolved_context != []


def test_prior_irrelevant_for_11min():
    # 11 分钟 > 10 分钟，不需要豁免判断，直接 40 元。
    rec = calculate_attendance(AttendanceInput(
        records=[_late(11)], exempt_context=_ctx())).records[0]
    assert rec.deduction == 40.0
    assert rec.exemption_applied is False


# ---------- 多记录 ----------

def test_multiple_records_accumulate():
    r = calculate_attendance(AttendanceInput(
        records=[_late(20, 1), _late(10, 2)],
        exempt_context=_ctx(late_prior_exempt=2)))
    assert len(r.records) == 2
    assert r.total_deduction == 60.0
    assert r.total_absence_days == 0.0


def test_mixed_late_and_early_separate_exempt_pools():
    r = calculate_attendance(AttendanceInput(
        records=[_late(8, 1), _early(8, 2)],
        exempt_context=_ctx(late_prior_exempt=0, early_leave_prior_exempt=0)))
    assert r.records[0].exemption_applied is True     # late 免
    assert r.records[1].exemption_applied is True     # early 免（各自独立池）
    assert r.total_deduction == 0.0


# ---------- 单位解析 ----------

@pytest.mark.parametrize("expr,minutes", [
    ("10分钟", 10), ("十分钟", 10), ("半小时", 30), ("半个小时", 30),
    ("1小时", 60), ("1.5小时", 90), ("10", 10),
])
def test_parse_duration_minutes_valid(expr, minutes):
    assert parse_duration_minutes(expr) == minutes


@pytest.mark.parametrize("expr", [
    "大概半小时", "迟到了一会", "有点晚", "0分钟", "-5", "没有数值", "",
])
def test_parse_duration_minutes_invalid(expr):
    assert parse_duration_minutes(expr) is None


# ---------- Golden 示例 ----------

def test_golden_example_1():
    r = calculate_attendance(AttendanceInput(
        records=[_late(20, 1), _late(10, 2)],
        exempt_context=_ctx(late_prior_exempt=2)))
    assert r.total_deduction == 60.0
    assert [x.deduction for x in r.records] == [40.0, 20.0]


def test_golden_example_2():
    r = calculate_attendance(AttendanceInput(
        records=[_late(65, 1), _late(10, 2)],
        exempt_context=_ctx(late_prior_exempt=2)))
    assert r.total_deduction == 20.0
    assert r.total_absence_days == 0.5
    assert r.records[0].absence_days == 0.5
    assert r.records[0].deduction == 0.0


def test_golden_example_3():
    r = calculate_attendance(AttendanceInput(records=[_early(250, 1)]))
    assert r.total_deduction == 0.0
    assert r.total_absence_days == 1.0
