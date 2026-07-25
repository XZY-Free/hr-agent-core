from hr_agent.tools.rules.leave_dates import calc_end_date

SCHED = [  # 7-27(日,休) 7-28..8-1(工作日) 8-2(六,休) 8-3(日,休) 8-4..8-8(工作日)
    {"shift_date": "2026-07-27", "shift_code": "OFF01"},
    *[{"shift_date": f"2026-07-{d}", "shift_code": "SCQY01"} for d in range(28, 32)],
    {"shift_date": "2026-08-01", "shift_code": "SCQY01"},
    {"shift_date": "2026-08-02", "shift_code": "off_day1"},
    {"shift_date": "2026-08-03", "shift_code": "defaultOFF"},
    *[{"shift_date": f"2026-08-0{d}", "shift_code": "SCQY01"} for d in range(4, 9)],
]


def test_continuous_type_counts_natural_days():
    r = calc_end_date("婚假", "2026-07-28", 5, SCHED)      # 连续计算
    assert r == {"start_date": "2026-07-28", "end_date": "2026-08-01", "mode": "continuous"}


def test_skip_rest_type_skips_off_days():
    r = calc_end_date("年休假", "2026-07-31", 3, SCHED)    # 跳过 8-2/8-3
    assert r["end_date"] == "2026-08-04" and r["mode"] == "skip_rest"


def test_unknown_type_falls_back_continuous():
    r = calc_end_date("神秘假", "2026-07-28", 2, SCHED)
    assert r["end_date"] == "2026-07-29" and r["mode"] == "continuous"


def test_over_27_days_shrinks_to_workdays():
    r = calc_end_date("事假", "2026-07-27", 30, SCHED)     # start 落在休息日→ 向后收缩
    assert r["start_date"] == "2026-07-28" and r["mode"] == "shrink_workday"


def test_start_outside_schedule_falls_back_natural():
    r = calc_end_date("年休假", "2026-09-01", 3, SCHED)    # 排班没有 9 月
    assert r["end_date"] == "2026-09-03" and r["mode"] == "skip_rest"


def test_half_day_continuous():
    # 0.5 天请假 → 占用 1 天，start=end
    r = calc_end_date("婚假", "2026-07-28", 0.5, SCHED)
    assert r["end_date"] == "2026-07-28" and r["mode"] == "continuous"


def test_unparseable_days_shrinks():
    r = calc_end_date("事假", "2026-07-28", float("nan"), SCHED)
    assert r["mode"] == "shrink_workday"
