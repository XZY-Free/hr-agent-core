"""leave_dates 规则测试：连续/跳休、三态排班、366 上限、离散连续性。

WP-02 §20 已删除 `>27 天 → shrink_workday`、未知排班当工作日、mode 字段等旧语义。
"""

import pytest

from packages.hr_domain.rules.leave_dates import (
    calendar_end,
    check_discrete_continuity,
    compute_leave_dates,
    compute_skip_rest_end,
    is_continuous_leave,
    next_known_workday,
)
from packages.hr_domain.schemas.schedule import (
    DayStatus,
    ScheduleDayTable,
    build_schedule_table,
)

SCHED = [  # 7-27(日,休) 7-28..8-1(工作日) 8-2(六,休) 8-3(日,休) 8-4..8-8(工作日)
    {"shift_date": "2026-07-27", "shift_code": "OFF01"},
    *[{"shift_date": f"2026-07-{d}", "shift_code": "SCQY01"} for d in range(28, 32)],
    {"shift_date": "2026-08-01", "shift_code": "SCQY01"},
    {"shift_date": "2026-08-02", "shift_code": "off_day1"},
    {"shift_date": "2026-08-03", "shift_code": "defaultOFF"},
    *[{"shift_date": f"2026-08-0{d}", "shift_code": "SCQY01"} for d in range(4, 9)],
]


def _table(items=SCHED):
    return build_schedule_table(items)


def test_continuous_type_counts_natural_days():
    r = compute_leave_dates(
        type_name="婚假", requested_start_date="2026-07-28",
        requested_end_date="2026-07-28", calendar_duration=5.0,
        workdays_requested=5, table=_table())
    assert r.start_date == "2026-07-28"
    assert r.end_date == "2026-08-01"


def test_skip_rest_type_skips_off_days():
    r = compute_leave_dates(
        type_name="年休假", requested_start_date="2026-07-31",
        requested_end_date="2026-07-31", calendar_duration=3.0,
        workdays_requested=3, table=_table())
    # 7-31 工作，8-2/8-3 休，累计 7-31/8-1/8-4
    assert r.end_date == "2026-08-04"
    assert r.error_code is None


def test_is_continuous_leave_defaults_true_for_unknown_type():
    assert is_continuous_leave("神秘假") is True


def test_over_27_days_continuous_no_shrink():
    # 连续自然日 30 天：end = start + 29，不触发任何 27 天收缩。
    r = compute_leave_dates(
        type_name="病假", requested_start_date="2026-01-01",
        requested_end_date="2026-01-01", calendar_duration=30.0,
        workdays_requested=30, table=_table())
    assert r.error_code is None
    assert r.end_date == "2026-01-30"


def test_over_27_days_skip_rest_counts_workdays():
    # 跳休 30 天：按已知工作日计数；排班只有 7-28..8-8，随后是 UNKNOWN。
    # WP-02：需要日期上的 UNKNOWN 不得跳过，故 fail-closed → schedule_unknown。
    r = compute_leave_dates(
        type_name="事假", requested_start_date="2026-07-28",
        requested_end_date="2026-07-28", calendar_duration=30.0,
        workdays_requested=30, table=_table())
    # 排班有 7-28..8-8 共 11 个工作日，30 个不够，且需要越过未知排班 → 报 schedule_unknown。
    assert r.error_code == "schedule_unknown"


def test_calendar_end_no_27_day_branch():
    assert calendar_end("2026-01-01", 98.0) == "2026-04-08"


def test_start_outside_schedule_unknown_not_workday():
    r = compute_leave_dates(
        type_name="年休假", requested_start_date="2026-09-01",
        requested_end_date="2026-09-01", calendar_duration=3.0,
        workdays_requested=3, table=_table())
    # 9 月不在排班 → 无 WORK 证据 → unknown，不把 9 月当工作日。
    assert r.error_code in ("schedule_unknown", "schedule_horizon_exceeded")


def test_half_day_continuous_same_day():
    r = compute_leave_dates(
        type_name="婚假", requested_start_date="2026-07-28",
        requested_end_date="2026-07-28", calendar_duration=0.5,
        workdays_requested=1, table=_table())
    assert r.end_date == "2026-07-28"


def test_next_known_workday_after_rest():
    assert next_known_workday("2026-07-27", _table()) == "2026-07-28"


def test_day_status_three_states():
    table = _table()
    assert table.day("2026-07-28") is DayStatus.WORK
    assert table.day("2026-07-27") is DayStatus.REST
    assert table.day("2026-09-01") is DayStatus.UNKNOWN


def test_discrete_continuity():
    rows = [
        {"shift_date": "2026-07-24", "shift_code": "SCQY01"},
        {"shift_date": "2026-07-25", "shift_code": "OFF01"},
        {"shift_date": "2026-07-26", "shift_code": "OFF01"},
        {"shift_date": "2026-07-27", "shift_code": "SCQY01"},
    ]
    ok, err = check_discrete_continuity(["2026-07-24", "2026-07-27"], build_schedule_table(rows))
    assert ok is True and err is None


def test_discrete_workday_gap():
    rows = [{"shift_date": f"2026-08-1{d}", "shift_code": "SCQY01"} for d in range(0, 6)]
    ok, err = check_discrete_continuity(["2026-08-10", "2026-08-15"], build_schedule_table(rows))
    assert ok is False and err == "discontinuous_workday_gap"
