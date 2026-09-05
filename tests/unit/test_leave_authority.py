"""WP-02 纯领域计算切片回归测试：权威日期/时段/时长/余额决定必须与显式请求
结构和注入的真实排班事实一致。

本文件只做领域断言，不实现生产逻辑、不触碰 session 持久化/Gaia 传输/UI/并发。
fixtures 全部是"排班输入事实 / 用户请求结构"，不是测试产出的计算结果。
本文件不声称已验证生产的端到端权限→性别→日期→时间→余额链路（那是后续接线切片）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from packages.hr_domain.rules.leave_dates import check_discrete_continuity
from packages.hr_domain.rules.leave_duration import (
    authoritative_duration,
    normalized_time_mode,
)
from packages.hr_domain.schemas.leave_draft import (
    DraftStatus,
    DurationUnit,
    TimeMode,
)
from packages.hr_domain.schemas.schedule import (
    DayStatus,
    ScheduleDayTable,
    ScheduleFact,
    build_schedule_table,
)
from packages.hr_domain.services.leave_draft_service import (
    compute_authoritative,
    detect_type_conflict,
    new_draft,
    normalize_type,
    validate_permission_gender_balance,
)


# ---------------------------------------------------------------- fixtures
WORK_CODE = "SCQY01"


def _work(d, start="08:00", end="18:00", meal_begin=None, meal_end=None):
    """工作日输入事实；无半天边界时 meal_begin/meal_end 均为 None。"""
    return {"shift_date": d, "shift_code": WORK_CODE, "start_time": start,
            "end_time": end, "meal_begin_time": meal_begin, "meal_end_time": meal_end}


def _rest(d):
    """休息日输入事实（00:00 记录，属于"非班次"，应回退 canonical 时段）。"""
    return {"shift_date": d, "shift_code": "OFF01", "start_time": "00:00",
            "end_time": "00:00", "meal_begin_time": None, "meal_end_time": None}


def _night(d):
    """夜班输入事实：19:00-07:00，参考半天边界 23:00-00:00。"""
    return {"shift_date": d, "shift_code": WORK_CODE, "start_time": "19:00",
            "end_time": "07:00", "meal_begin_time": "23:00", "meal_end_time": "00:00"}


def _full_day_authority(type_name="年休假", start="2026-09-07"):
    """经真实 compute_authoritative 产出的完整草稿（单日 FULL_DAY）。"""
    draft = new_draft(f"auth-{type_name}-{start}")
    normalize_type(draft, type_name)
    draft.requested_start_date = start
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 1.0
    draft.duration_unit = DurationUnit.DAY
    compute_authoritative(draft, table=build_schedule_table([_work(start)]))
    return draft


def _hours_range_authority(start_time="16:00", end_time="18:00", start="2026-09-07"):
    """经真实 compute_authoritative 产出的完整草稿（小时区间 EXPLICIT_RANGE）。"""
    draft = new_draft(f"auth-hour-{start}")
    normalize_type(draft, "年休假")
    draft.requested_start_date = start
    draft.time_mode = TimeMode.EXPLICIT_RANGE
    draft.requested_start_time = start_time
    draft.requested_end_time = end_time
    compute_authoritative(draft, table=build_schedule_table([_work(start)]))
    return draft


# ------------------------------------------- 权威时长/日期以草稿意图为权威
def test_annual_3day_request_yields_3_days():
    """3 天年休假 9-7..9-9：权威日期与时长取草稿意图 3，而不是默认 1。"""
    draft = new_draft("d1")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 3.0
    draft.duration_unit = DurationUnit.DAY
    table = build_schedule_table([_work("2026-09-07"), _work("2026-09-08"), _work("2026-09-09")])
    compute_authoritative(draft, table=table)  # 不传 calendar_duration / workdays
    assert draft.authoritative_start_date == "2026-09-07"
    assert draft.authoritative_end_date == "2026-09-09"
    assert draft.authoritative_duration_value == 3.0
    assert draft.authoritative_duration_unit is DurationUnit.DAY


def test_explicit_range_dates_override_claimed_duration():
    """显式范围 9-7..9-9，宣称 9 天：权威日期/时长按真实范围 = 3，不采信 9。"""
    draft = new_draft("d2")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.requested_end_date = "2026-09-09"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 9.0
    draft.duration_unit = DurationUnit.DAY
    table = build_schedule_table([_work("2026-09-07"), _work("2026-09-08"), _work("2026-09-09")])
    compute_authoritative(draft, table=table)
    assert draft.authoritative_start_date == "2026-09-07"
    assert draft.authoritative_end_date == "2026-09-09"
    assert draft.authoritative_duration_value == 3.0


def test_weekend_rest_then_two_workdays_monday_start():
    """周末 9-5/9-6 休息、9-7/9-8 工作日：两天年休假应 Mon 起 Tue 止，时长 2。"""
    draft = new_draft("d3")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-05"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 2.0
    draft.duration_unit = DurationUnit.DAY
    table = build_schedule_table(
        [_rest("2026-09-05"), _rest("2026-09-06"), _work("2026-09-07"), _work("2026-09-08")]
    )
    result = compute_authoritative(draft, table=table)
    assert result.status != DraftStatus.VALIDATION_FAILED
    assert draft.authoritative_start_date == "2026-09-07"
    assert draft.authoritative_end_date == "2026-09-08"
    assert draft.authoritative_duration_value == 2.0


def test_maternity_98_days_no_27_limit_canonical_rest_time():
    """产假 98 天连续自然日，无 27 天上限；休息日回退 canonical 08:00-18:00。"""
    draft = new_draft("d4")
    normalize_type(draft, "产假")
    draft.requested_start_date = "2026-01-01"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 98.0
    draft.duration_unit = DurationUnit.DAY
    # 一次性提供 98 天全量排班事实，避免"落回 UNKNOWN 兜底"成为借口
    facts = [_rest((date(2026, 1, 1) + timedelta(days=i)).isoformat()) for i in range(98)]
    result = compute_authoritative(draft, table=build_schedule_table(facts))
    assert result.status == DraftStatus.READY_FOR_VALIDATION
    assert draft.authoritative_end_date == "2026-04-08"          # start + 97
    assert draft.authoritative_duration_value == 98.0
    assert draft.authoritative_start_time == "08:00"             # canonical，不是休息记录 00:00
    assert draft.authoritative_end_time == "18:00"


def test_1_5_days_is_full_first_plus_first_half_final_no_round_up():
    """1.5 天 = 首日整天 + 末日第一个半天；不得四舍五入到 2 天，末半天止时间=12:00。"""
    draft = new_draft("d5")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 1.5
    draft.duration_unit = DurationUnit.DAY
    table = build_schedule_table([
        _work("2026-09-07", meal_begin="12:00", meal_end="13:00"),
        _work("2026-09-08", meal_begin="12:00", meal_end="13:00"),
    ])
    result = compute_authoritative(draft, table=table)
    assert result.status == DraftStatus.READY_FOR_VALIDATION
    assert draft.authoritative_end_date == "2026-09-08"
    assert draft.authoritative_duration_value == 1.5
    assert draft.authoritative_start_time == "08:00"
    assert draft.authoritative_end_time == "12:00"                # 末日第一个半天


# ------------------------------------------- status / 部分写保护
def test_returned_status_agrees_with_state_status():
    """compute_authoritative 返回的 status 必须写回 draft.status。"""
    draft = new_draft("d6")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FULL_DAY
    table = build_schedule_table([_work("2026-09-07")])
    result = compute_authoritative(draft, table=table)
    assert result.state.status == result.status


def test_no_partial_authority_on_duration_failure():
    """时长计算失败（无半天边界）时不得部分写入任何权威字段。"""
    draft = new_draft("d7")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FIRST_HALF
    table = build_schedule_table([_work("2026-09-07")])  # 无 meal/middle 边界
    result = compute_authoritative(draft, table=table)
    assert result.error_code == "schedule_detail_insufficient"
    assert result.status == DraftStatus.VALIDATION_FAILED
    assert draft.authoritative_start_date is None
    assert draft.authoritative_end_date is None
    assert draft.authoritative_duration_value is None
    assert draft.authoritative_start_time is None
    assert draft.authoritative_end_time is None


# ------------------------------------------- normalize_type 失效
def test_invalid_replacement_clears_stale_normalized_name():
    """无效类型替换必须清除旧的 normalized_type_name，不允许残留旧正式名。"""
    draft = new_draft("d8")
    normalize_type(draft, "年休假")
    assert draft.normalized_type_name == "年休假"
    normalize_type(draft, "环球旅游假")
    assert draft.normalized_type_name is None
    assert draft.type_code is None


def test_subtype_names_not_false_conflict():
    """多假种冲突不得因子串（陪产假 ⊃ 产假）误报单一类型为冲突。"""
    assert detect_type_conflict("陪产假") is False
    assert detect_type_conflict("请三天陪产假") is False
    assert detect_type_conflict("年假和事假") is True


# ------------------------------------------- 排班事实三态
def test_empty_shift_code_is_unknown_not_work():
    """空缺 shift_code 的排班记录应视为 UNKNOWN，不得当作 WORK。"""
    fact = ScheduleFact(shift_date="2026-09-07", shift_code="", start_time="", end_time="")
    table = ScheduleDayTable([fact])
    assert table.day("2026-09-07") is DayStatus.UNKNOWN


def test_none_shift_code_is_unknown_not_crash():
    """shift_code=None 不得崩溃，应回退为 UNKNOWN。"""
    fact = ScheduleFact(shift_date="2026-09-07", shift_code=None, start_time="", end_time="")  # type: ignore[arg-type]
    table = ScheduleDayTable([fact])
    assert table.day("2026-09-07") is DayStatus.UNKNOWN


# ------------------------------------------- 权限→性别→余额 不静默放行
def test_missing_balance_not_silently_allowed():
    """余额缺失（balance=None）应明确拒绝，错误码 balance_unknown。"""
    draft = _full_day_authority()
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M", balance=None)
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "balance_unknown"


def test_missing_sex_not_silently_allowed_for_gender_leave():
    """限制性别假（产假）缺失性别应明确拒绝，错误码 gender_unknown。"""
    draft = _full_day_authority(type_name="产假")
    result = validate_permission_gender_balance(
        draft, allowed_types=["产假"], sex=None,
        balance=[{"leave_name": "产假", "remain": 98, "unit": DurationUnit.DAY.value}])
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "gender_unknown"


def test_unit_mismatch_hour_request_day_balance_rejected():
    """小时请求 vs 天单位余额：禁止单位混算，错误码 unit_mismatch。"""
    draft = _hours_range_authority()  # 16:00-18:00 → 2.0 hour
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "年休假", "remain": 10, "unit": DurationUnit.DAY.value}])
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "unit_mismatch"


def test_unit_mismatch_day_request_hour_balance_rejected():
    """天请求 vs 小时单位余额：禁止单位混算，错误码 unit_mismatch。"""
    draft = _full_day_authority()  # 1.0 day
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "年休假", "remain": 24, "unit": DurationUnit.HOUR.value}])
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "unit_mismatch"


def test_missing_request_duration_unit_fails_closed():
    """权威时长缺单位（malformed authority）应 fail-closed，错误码 duration_unit_unknown。"""
    draft = _full_day_authority()
    draft.authoritative_duration_unit = None  # 模拟畸形权威时长
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "年休假", "remain": 10, "unit": DurationUnit.DAY.value}])
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "duration_unit_unknown"


def test_balance_row_missing_unit_not_silently_allowed():
    """余额行缺单位应 fail-closed，错误码 balance_unit_unknown。"""
    draft = _full_day_authority()
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "年休假", "remain": 10}])
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "balance_unit_unknown"


def test_wrong_leave_balance_row_not_borrowed():
    """余额行 leave_name 与请求类型不符时不得借用，错误码 balance_unknown。"""
    draft = _full_day_authority()
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "事假", "remain": 10, "unit": DurationUnit.DAY.value}])
    assert result.status != DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code == "balance_unknown"


def test_matched_unit_complete_draft_passes_to_confirmation():
    """完整草稿 + 匹配单位余额：应通过到 ready_for_confirmation（对照绿灯）。"""
    draft = _full_day_authority()
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "年休假", "remain": 10, "unit": DurationUnit.DAY.value}])
    assert result.status == DraftStatus.READY_FOR_CONFIRMATION
    assert result.error_code is None


def test_insufficient_balance_from_real_3day_compute():
    """经真实 compute 得到 3 天意图、余额 2 天：应明确拒绝 insufficient_balance。"""
    draft = new_draft("i1")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 3.0
    draft.duration_unit = DurationUnit.DAY
    table = build_schedule_table([_work("2026-09-07"), _work("2026-09-08"), _work("2026-09-09")])
    compute_authoritative(draft, table=table)  # 不手工填充权威时长
    result = validate_permission_gender_balance(
        draft, allowed_types=["年休假"], sex="M",
        balance=[{"leave_name": "年休假", "remain": 2, "unit": DurationUnit.DAY.value}])
    assert result.status == DraftStatus.VALIDATION_FAILED
    assert result.error_code == "insufficient_balance"


# ------------------------------------------- 时间/时长边界 fail-closed
def test_invalid_time_24_70_fails_closed():
    """非法时间 24:70 应拒绝，而非解析出小时数。"""
    result = authoritative_duration(
        time_mode=TimeMode.EXPLICIT_RANGE, schedule_fact=None,
        requested_start_time="24:70", requested_end_time="23:00", requested_hours=None)
    assert result.duration_value is None
    assert result.error_code is not None


@pytest.mark.parametrize("hours", [float("nan"), float("inf")])
def test_nonfinite_hours_fail_closed(hours):
    """NaN / inf 小时数应 fail-closed。"""
    result = authoritative_duration(
        time_mode=TimeMode.EXPLICIT_HOURS, schedule_fact=None,
        requested_start_time=None, requested_end_time=None, requested_hours=hours)
    assert result.duration_value is None
    assert result.error_code is not None


@pytest.mark.parametrize("hours", [0, -1])
def test_nonpositive_hours_fail_closed(hours):
    """0 / 负小时数应拒绝（此场景已正确）。"""
    result = authoritative_duration(
        time_mode=TimeMode.EXPLICIT_HOURS, schedule_fact=None,
        requested_start_time=None, requested_end_time=None, requested_hours=hours)
    assert result.error_code == "invalid_hours"


@pytest.mark.parametrize("days", [0.0, -2.0, float("nan")])
def test_day_duration_nonpositive_fails_closed(days):
    """0 / 负 / 非有限天时长应 fail-closed，而非退回默认 1 天。"""
    draft = new_draft("d-dur")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = days
    draft.duration_unit = DurationUnit.DAY
    table = build_schedule_table([_work("2026-09-07")])
    result = compute_authoritative(draft, table=table)
    assert result.status != DraftStatus.READY_FOR_VALIDATION


def test_one_anchor_hours_derives_end_time():
    """一个时间锚点 + 小时数应推导出另一端（16:00+2h=18:00），且落在班次内。"""
    draft = new_draft("h1")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.EXPLICIT_HOURS
    draft.requested_start_time = "16:00"
    draft.requested_hours = 2.0
    result = compute_authoritative(draft, table=build_schedule_table([_work("2026-09-07")]))
    assert result.status == DraftStatus.READY_FOR_VALIDATION
    assert draft.authoritative_start_time == "16:00"
    assert draft.authoritative_end_time == "18:00"               # 由锚点+小时数推导
    assert draft.authoritative_duration_value == 2.0


def test_out_of_shift_hours_rejected():
    """锚点 16:00 + 10h 超出班次（08:00-18:00）：应拒绝，不得假造锚点穿越跨天。"""
    draft = new_draft("h2")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.EXPLICIT_HOURS
    draft.requested_start_time = "16:00"
    draft.requested_hours = 10.0
    result = compute_authoritative(draft, table=build_schedule_table([_work("2026-09-07")]))
    assert result.status != DraftStatus.READY_FOR_VALIDATION


def test_full_compute_range_fits_actual_shift():
    """完整计算路径：显式 16:00-18:00 落在班次内 → 2 小时，hour 单位。"""
    draft = new_draft("h3")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.EXPLICIT_RANGE
    draft.requested_start_time = "16:00"
    draft.requested_end_time = "18:00"
    result = compute_authoritative(draft, table=build_schedule_table([_work("2026-09-07")]))
    assert result.status == DraftStatus.READY_FOR_VALIDATION
    assert draft.authoritative_duration_value == 2.0
    assert draft.authoritative_duration_unit is DurationUnit.HOUR


def test_range_out_of_shift_rejected():
    """完整计算路径：显式 08:00-22:00 超出班次（08:00-18:00）应拒绝。"""
    draft = new_draft("h4")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.EXPLICIT_RANGE
    draft.requested_start_time = "08:00"
    draft.requested_end_time = "22:00"
    result = compute_authoritative(draft, table=build_schedule_table([_work("2026-09-07")]))
    assert result.status != DraftStatus.READY_FOR_VALIDATION


def test_explicit_hours_without_time_anchor_collecting():
    """仅小时数、无时间锚点：仍在收集，不允许假造锚点并标已完成。"""
    draft = new_draft("h5")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.EXPLICIT_HOURS
    draft.requested_hours = 2.0
    result = compute_authoritative(draft, table=build_schedule_table([_work("2026-09-07")]))
    assert result.status == DraftStatus.COLLECTING
    assert result.missing.time_or_duration is True


# ------------------------------------------- 夜班与半天
def test_night_19_07_ends_next_date():
    """夜班 19:00-07:00 跨天：结束日期 +1，时长 12 小时。"""
    draft = new_draft("n1")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.EXPLICIT_RANGE
    draft.requested_start_time = "19:00"
    draft.requested_end_time = "07:00"
    result = compute_authoritative(draft, table=build_schedule_table([_night("2026-09-07")]))
    assert result.status == DraftStatus.READY_FOR_VALIDATION
    assert draft.authoritative_start_date == "2026-09-07"
    assert draft.authoritative_end_date == "2026-09-08"
    assert draft.authoritative_duration_value == 12.0
    assert draft.authoritative_duration_unit is DurationUnit.HOUR


def test_second_half_after_midnight_starts_next_date():
    """夜班第二个半天 00:00-07:00 属次日：起始/结束日期都落在 2026-09-08。"""
    draft = new_draft("n2")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.SECOND_HALF
    result = compute_authoritative(draft, table=build_schedule_table([_night("2026-09-07")]))
    assert draft.authoritative_start_date == "2026-09-08"
    assert draft.authoritative_end_date == "2026-09-08"
    assert draft.authoritative_start_time == "00:00"
    assert draft.authoritative_end_time == "07:00"


def test_half_day_uses_actual_meal_boundary():
    """半天使用 Gaia meal/middle 边界，而非硬编 12:00。"""
    table = build_schedule_table([_work("2026-09-07", meal_begin="11:30", meal_end="13:30")])
    fact = table.fact("2026-09-07")
    first = authoritative_duration(
        time_mode=TimeMode.FIRST_HALF, schedule_fact=fact,
        requested_start_time=None, requested_end_time=None, requested_hours=None)
    assert first.end_time == "11:30"
    second = authoritative_duration(
        time_mode=TimeMode.SECOND_HALF, schedule_fact=fact,
        requested_start_time=None, requested_end_time=None, requested_hours=None)
    assert second.start_time == "13:30"


def test_bare_half_day_defaults_first_half():
    """裸 0.5 天未指明上/下午，默认第一个半天。"""
    assert normalized_time_mode() is TimeMode.FIRST_HALF


# ------------------------------------------- 离散日期（requested_date_segments）
def test_discrete_fri_mon_known_rest_spans_both_days():
    """离散 Fri+Mon、周末已知休息——权威日期应覆盖两日（9-04..9-07），时长 2。"""
    draft = new_draft("seg1")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-04"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 2.0
    draft.duration_unit = DurationUnit.DAY
    draft.requested_date_segments = ["2026-09-04", "2026-09-07"]
    rows = [_work("2026-09-04"), _rest("2026-09-05"), _rest("2026-09-06"), _work("2026-09-07")]
    compute_authoritative(draft, table=build_schedule_table(rows),
                          requested_segments=draft.requested_date_segments)
    assert draft.authoritative_start_date == "2026-09-04"
    assert draft.authoritative_end_date == "2026-09-07"
    assert draft.authoritative_duration_value == 2.0


def test_discrete_workday_gap_rejected_via_draft():
    """离散 Fri+Mon、中间是工作日：经完整草稿判定不连续。"""
    draft = new_draft("seg2")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-04"
    draft.time_mode = TimeMode.FULL_DAY
    draft.requested_date_segments = ["2026-09-04", "2026-09-07"]
    rows = [_work("2026-09-04"), _work("2026-09-05"), _work("2026-09-06"), _work("2026-09-07")]
    result = compute_authoritative(draft, table=build_schedule_table(rows),
                                   requested_segments=draft.requested_date_segments)
    assert result.status == DraftStatus.VALIDATION_FAILED
    assert result.error_code == "discontinuous_workday_gap"


def test_discrete_unknown_gap_fail_closed_via_draft():
    """离散 Fri+Mon、中间排班未知：不得武断判连续。"""
    draft = new_draft("seg3")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-04"
    draft.time_mode = TimeMode.FULL_DAY
    draft.requested_date_segments = ["2026-09-04", "2026-09-07"]
    rows = [_work("2026-09-04"), _work("2026-09-07")]
    result = compute_authoritative(draft, table=build_schedule_table(rows),
                                   requested_segments=draft.requested_date_segments)
    assert result.status == DraftStatus.VALIDATION_FAILED
    assert result.error_code == "schedule_unknown_for_continuity"


def test_unknown_in_needed_skip_rest_date_fails_not_jumpahead():
    """跳休累计到工作日前遇到 UNKNOWN：不得跳过并向后"跃迁"，应 fail-closed。"""
    draft = new_draft("unk1")
    normalize_type(draft, "年休假")
    draft.requested_start_date = "2026-09-07"
    draft.time_mode = TimeMode.FULL_DAY
    draft.duration_value = 2.0
    draft.duration_unit = DurationUnit.DAY
    # 9-7 WORK、9-8 UNKNOWN、9-9 WORK：第 2 个工作日落在未知日，不能跳到 9-9
    rows = [_work("2026-09-07"), _work("2026-09-09")]
    result = compute_authoritative(draft, table=build_schedule_table(rows),
                                   workdays_requested=2)
    assert result.status != DraftStatus.READY_FOR_VALIDATION


# ------------------------------------------- 离散连续性 helper（保留）
def test_discrete_known_rest_gap_accepted():
    """离散 Fri+Mon，中间是已知休息日：视为连续。"""
    rows = [_work("2026-09-04"), _rest("2026-09-05"), _rest("2026-09-06"), _work("2026-09-07")]
    ok, err = check_discrete_continuity(["2026-09-04", "2026-09-07"], build_schedule_table(rows))
    assert ok is True and err is None


def test_discrete_workday_gap_rejected():
    """离散 Fri+Mon，中间是工作日：判定不连续。"""
    rows = [_work("2026-09-04"), _work("2026-09-05"), _work("2026-09-06"), _work("2026-09-07")]
    ok, err = check_discrete_continuity(["2026-09-04", "2026-09-07"], build_schedule_table(rows))
    assert ok is False and err == "discontinuous_workday_gap"


def test_discrete_unknown_gap_fail_closed():
    """离散 Fri+Mon，中间排班未知：不得武断判连续。"""
    rows = [_work("2026-09-04"), _work("2026-09-07")]
    ok, err = check_discrete_continuity(["2026-09-04", "2026-09-07"], build_schedule_table(rows))
    assert ok is False and err == "schedule_unknown_for_continuity"
