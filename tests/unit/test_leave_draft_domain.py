"""WP-02 Leave Draft 领域规则测试：标准化、连续/跳休、时长、连续性、多假种冲突。"""

import pytest

from packages.hr_domain.constants.leave_rules import normalize_type_name, HOLIDAY_TYPE_CODE
from packages.hr_domain.schemas.leave_draft import (
    DurationUnit,
    FieldSource,
    TimeMode,
)
from packages.hr_domain.schemas.schedule import DayStatus, build_schedule_table
from packages.hr_domain.rules.leave_dates import (
    compute_leave_dates,
    check_discrete_continuity,
    is_continuous_leave,
    calendar_end,
    compute_skip_rest_end,
)
from packages.hr_domain.rules.leave_duration import (
    authoritative_duration,
    normalized_time_mode,
)
from packages.hr_domain.services.leave_draft_service import (
    compute_authoritative,
    compute_missing_fields,
    new_draft,
    normalize_type,
    validate_permission_gender_balance,
)


# ---------- 假种标准化 ----------

@pytest.mark.parametrize("raw,expected", [
    ("年假", "年休假"), ("调休", "调休假"), ("年休假", "年休假"),
    ("事假", "事假"), ("年休", "年休假"), ("育儿假", "育儿假"),
])
def test_normalize_type_name(raw, expected):
    assert normalize_type_name(raw) == expected


def test_unknown_type_rejected():
    assert normalize_type_name("环球旅游假") is None


def test_type_code_comes_from_holiday_map():
    name = normalize_type_name("年假")
    assert name == "年休假"
    assert HOLIDAY_TYPE_CODE[name] == "A31"


def test_type_source_is_normalized_not_model():
    draft = new_draft("d1")
    normalize_type(draft, "年假")
    assert draft.normalized_type_name == "年休假"
    assert draft.type_source is FieldSource.NORMALIZED_USER
    assert draft.type_code == "A31"


# ---------- 连续自然日 ----------

def _work_day(d, code="SCQY01", start="08:00", end="17:00"):
    return {"shift_date": d, "shift_code": code, "shift_name": "班",
            "start_time": start, "end_time": end}


def _rest_day(d):
    return {"shift_date": d, "shift_code": "OFF01", "shift_name": "休息",
            "start_time": "00:00", "end_time": "00:00"}


def test_continuous_leave_true_for_maternity():
    assert is_continuous_leave("产假") is True
    assert is_continuous_leave("病假") is True
    assert is_continuous_leave("年休假") is False


def test_maternity_starting_saturday_rest_is_allowed():
    rows = [_rest_day("2026-07-25")]
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="产假", requested_start_date="2026-07-25",
        requested_end_date="2026-07-25", calendar_duration=1.0,
        workdays_requested=1, table=table)
    assert r.error_code is None
    assert r.start_date == "2026-07-25"  # 不因休息日改期


def test_maternity_98_days_no_27_day_limit():
    rows = []
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="产假", requested_start_date="2026-01-01",
        requested_end_date="2026-01-01", calendar_duration=98.0,
        workdays_requested=98, table=table)
    assert r.error_code is None
    assert r.end_date == calendar_end("2026-01-01", 98.0)


def test_continuous_crosses_multiple_rest_days():
    # 连续假跨多个休息日，日期连续，不因 REST 中断。
    rows = [_rest_day("2026-07-25"), _rest_day("2026-07-26"), _work_day("2026-07-27")]
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="病假", requested_start_date="2026-07-25",
        requested_end_date="2026-07-27", calendar_duration=3.0,
        workdays_requested=3, table=table)
    assert r.error_code is None
    assert r.end_date == "2026-07-27"


# ---------- 跳休 ----------

def test_skip_rest_single_rest_day_rejected():
    rows = [_rest_day("2026-07-25")]
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="年休假", requested_start_date="2026-07-25",
        requested_end_date="2026-07-25", calendar_duration=1.0,
        workdays_requested=1, table=table)
    assert r.error_code == "rest_day"


def test_skip_rest_saturday_start_counts_from_first_workday():
    rows = [_rest_day("2026-07-25"), _work_day("2026-07-27"), _work_day("2026-07-28")]
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="年休假", requested_start_date="2026-07-25",
        requested_end_date="", calendar_duration=2.0,
        workdays_requested=2, table=table)
    assert r.start_date == "2026-07-27"
    assert r.end_date == "2026-07-28"


def test_skip_rest_friday_plus_monday_over_weekend():
    rows = [_work_day("2026-07-24"), _rest_day("2026-07-25"), _rest_day("2026-07-26"),
            _work_day("2026-07-27")]
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="年休假", requested_start_date="2026-07-24",
        requested_end_date="", calendar_duration=2.0,
        workdays_requested=2, table=table)
    assert r.start_date == "2026-07-24"
    assert r.end_date == "2026-07-27"


def test_skip_rest_unknown_future_not_treated_as_workday():
    # 只查到周五 WORK，后续未知；不得把周六/周日/周一当工作日。
    rows = [_work_day("2026-07-24")]
    table = build_schedule_table(rows)
    r = compute_leave_dates(
        type_name="年休假", requested_start_date="2026-07-24",
        requested_end_date="", calendar_duration=2.0,
        workdays_requested=2, table=table)
    assert r.error_code in ("schedule_unknown", "schedule_horizon_exceeded")
    assert r.end_date == "2026-07-24"  # 不足 WORK 时不得向后凑工作日照成更晚日期


# ---------- 时长 ----------

def _day_fact(code="SCQY01", start="08:00", end="17:00", meal_begin="12:00", meal_end="13:00"):
    return {"shift_date": "2026-07-27", "shift_code": code, "shift_name": "班",
            "start_time": start, "end_time": end,
            "meal_begin_time": meal_begin, "meal_end_time": meal_end}


def _no_boundary_fact():
    return {"shift_date": "2026-07-27", "shift_code": "SCQY01", "shift_name": "班",
            "start_time": "08:00", "end_time": "17:00",
            "meal_begin_time": None, "meal_end_time": None}



def test_full_day_uses_shift():
    table = build_schedule_table([_day_fact()])
    fact = table.fact("2026-07-27")
    r = authoritative_duration(
        time_mode=TimeMode.FULL_DAY, schedule_fact=fact,
        requested_start_time=None, requested_end_time=None, requested_hours=None)
    assert r.duration_value == 1.0 and r.duration_unit is DurationUnit.DAY
    assert r.start_time == "08:00" and r.end_time == "17:00"


def test_first_half_uses_meal_begin():
    table = build_schedule_table([_day_fact()])
    fact = table.fact("2026-07-27")
    r = authoritative_duration(
        time_mode=TimeMode.FIRST_HALF, schedule_fact=fact,
        requested_start_time=None, requested_end_time=None, requested_hours=None)
    assert r.duration_value == 0.5 and r.duration_unit is DurationUnit.DAY
    assert r.end_time == "12:00"  # meal_begin_time


def test_second_half_uses_meal_end():
    table = build_schedule_table([_day_fact()])
    fact = table.fact("2026-07-27")
    r = authoritative_duration(
        time_mode=TimeMode.SECOND_HALF, schedule_fact=fact,
        requested_start_time=None, requested_end_time=None, requested_hours=None)
    assert r.start_time == "13:00"


def test_bare_half_day_defaults_first_half():
    m = normalized_time_mode()  # 无任何标记 → bare 0.5
    assert m is TimeMode.FIRST_HALF


def test_explicit_two_hours_keeps_hour_unit():
    r = authoritative_duration(
        time_mode=TimeMode.EXPLICIT_HOURS, schedule_fact=None,
        requested_start_time="16:00", requested_end_time=None, requested_hours=2.0)
    assert r.duration_value == 2.0 and r.duration_unit is DurationUnit.HOUR


def test_half_day_without_boundary_is_insufficient():
    table = build_schedule_table([_no_boundary_fact()])
    fact = table.fact("2026-07-27")
    r = authoritative_duration(
        time_mode=TimeMode.FIRST_HALF, schedule_fact=fact,
        requested_start_time=None, requested_end_time=None, requested_hours=None)
    assert r.error_code == "schedule_detail_insufficient"


# ---------- 连续性 ----------

def test_discrete_friday_monday_weekend_gap_continuous():
    rows = [_rest_day("2026-07-25"), _rest_day("2026-07-26"),
            _work_day("2026-07-24"), _work_day("2026-07-27")]
    table = build_schedule_table(rows)
    ok, err = check_discrete_continuity(["2026-07-24", "2026-07-27"], table)
    assert ok is True and err is None


def test_discrete_workday_gap_discontinuous():
    rows = [_work_day("2026-07-10"), _work_day("2026-07-11"),
            _work_day("2026-07-12"), _work_day("2026-07-13"),
            _work_day("2026-07-14"), _work_day("2026-07-15")]
    table = build_schedule_table(rows)
    ok, err = check_discrete_continuity(["2026-07-10", "2026-07-11", "2026-07-15"], table)
    assert ok is False and err == "discontinuous_workday_gap"


def test_discrete_unknown_gap_not_asserted_continuous():
    rows = [_work_day("2026-07-10")]
    table = build_schedule_table(rows)
    ok, err = check_discrete_continuity(["2026-07-10", "2026-07-15"], table)
    assert ok is False and err == "schedule_unknown_for_continuity"


# ---------- 多假种冲突（detect_multi_type_conflict） ----------

def test_multi_type_conflict_detected():
    from packages.hr_domain.services.leave_draft_service import (
        detect_type_conflict,
    )
    assert detect_type_conflict("年假和事假") is True
    assert detect_type_conflict("病假或者年假都行") is True
    assert detect_type_conflict("请两天年假") is False


# ---------- Draft 缺槽位 ----------

def test_missing_fields_when_nothing_given():
    draft = new_draft("d1")
    m = compute_missing_fields(draft)
    assert m.type_name and m.date and m.time_or_duration
    assert not m.reason  # 理由非必填，未提供不算缺失


def test_missing_after_type_not_date():
    draft = new_draft("d1")
    normalize_type(draft, "年假")
    draft.requested_start_date = "2026-07-27"
    draft.time_mode = TimeMode.FULL_DAY
    m = compute_missing_fields(draft)
    assert not m.type_name
    assert m.date or m.time_or_duration  # 尚未计算权威日期，仍视为缺失


def test_reason_empty_not_fabricated():
    draft = new_draft("d1")
    assert draft.reason is None
    assert draft.reason_source is None
