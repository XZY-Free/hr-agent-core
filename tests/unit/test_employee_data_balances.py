"""WP-03 本人数据能力恢复测试：多假种余额、单位、年份、not_found、语义区分。"""

import pytest

from apps.employee_data_agent.provider import (
    GaiaEmployeeDataProvider,
    StubEmployeeDataProvider,
)
from apps.employee_data_agent.runtime import (
    _extract_target,
    _query_type,
    _render_all_balances,
    _render_single_balance,
    _select_data,
)


# ---------- Provider leave_balances ----------

def test_stub_leave_balances_all():
    records = {"EMP-001": {"leave_balances": [
        {"leave_code": "A31", "leave_name": "年休假", "unit": "day",
         "effective_year": "2026", "total": 5, "used": 1, "remain": 4},
        {"leave_code": "A47", "leave_name": "育儿假", "unit": "day",
         "effective_year": "2026", "total": 10, "used": 0, "remain": 10},
    ]}}
    provider = StubEmployeeDataProvider(records)
    r = provider.leave_balances("EMP-001")
    assert r.source == "stub"
    assert len(r.data["leave_balances"]) == 2


def test_stub_leave_balances_by_type_filters():
    records = {"EMP-001": {"leave_balances": [
        {"leave_name": "年休假", "unit": "day", "remain": 4},
        {"leave_name": "育儿假", "unit": "day", "remain": 10},
    ]}}
    provider = StubEmployeeDataProvider(records)
    r = provider.leave_balances("EMP-001", "育儿假")
    assert [x["leave_name"] for x in r.data["leave_balances"]] == ["育儿假"]


def test_stub_leave_balances_not_found():
    provider = StubEmployeeDataProvider({})
    r = provider.leave_balances("EMP-404")
    assert r.error_code == "employee_not_found"


# ---------- Runtime query_type 语义 ----------

@pytest.mark.parametrize("message,expected", [
    ("我还有几天育儿假", "leave_balance_by_type"),
    ("我的假期余额", "leave_balance_all"),
    ("我所有假还剩多少", "leave_balance_all"),
    ("我的医疗期余额", "medical_period"),
    ("我的年假怎么折算", "annual_leave_calculation"),
    ("四川育儿假有几天", None),          # 政策问句 → Consult
    ("育儿假怎么申请", "leave_balance_by_type"),  # 会被前置 reject 拦截
    ("我的工龄", "employment_info"),
])
def test_query_type_semantics(message, expected):
    assert _query_type(message) == expected


def test_target_standardization():
    assert _extract_target("我还有几天育儿假") == "育儿假"
    assert _extract_target("我还剩多少年假") == "年休假"
    assert _extract_target("我的调休还有多少") == "调休假"


# ---------- Runtime 渲染 ----------

def test_render_single_day_unit():
    rows = [{"leave_name": "年休假", "unit": "day", "remain": 4}]
    data, answer, err = _select_data("leave_balance_by_type",
                                     {"leave_balances": rows}, "年休假")
    assert err is None
    assert "4 天" in answer
    assert data["leave_balance"]["remain"] == 4


def test_render_single_hour_unit():
    rows = [{"leave_name": "调休假", "unit": "hour", "remain": 2}]
    data, answer, err = _select_data("leave_balance_by_type",
                                     {"leave_balances": rows}, "调休假")
    assert err is None
    assert "2 小时" in answer


def test_render_single_not_found_no_first_row_fallback():
    rows = [{"leave_name": "年休假", "unit": "day", "remain": 4}]
    data, answer, err = _select_data("leave_balance_by_type",
                                     {"leave_balances": rows}, "育儿假")
    assert err == "leave_balance_not_found"
    assert data is None


def test_render_all_mixed_units_and_years():
    rows = [
        {"leave_name": "年休假", "unit": "day", "remain": 4, "effective_year": "2025"},
        {"leave_name": "调休假", "unit": "hour", "remain": 2, "effective_year": ""},
    ]
    data, answer, err = _select_data("leave_balance_all", {"leave_balances": rows})
    assert err is None
    assert "年休假：4 天（2025年）" in answer
    assert "调休假：2 小时" in answer


def test_render_all_empty_not_found():
    data, answer, err = _select_data("leave_balance_all", {"leave_balances": []})
    assert err == "leave_balance_not_found"


def test_render_no_8_hour_hard_conversion():
    # 2 小时不得渲染成 0.25 天 / 不得当为 8 小时=1 天。
    rows = [{"leave_name": "调休假", "unit": "hour", "remain": 2}]
    _, answer, err = _select_data("leave_balance_by_type",
                                  {"leave_balances": rows}, "调休假")
    assert "2 小时" in answer
    assert "天" not in answer.replace("调休假", "")


# ---------- annual_profile 组合（保留已有能力） ----------

def test_annual_profile_still_works_with_compute():
    class FakeGaia:
        def employee_info(self, employee_id):
            return {"success": True, "data": {"social_service_year": "6",
                                               "social_service_month": "0",
                                               "social_service_day": "0",
                                               "hire_month": "11", "hire_day": "03"}}

        def leave_balance(self, leave_type, employee_id):
            return {"success": True, "data": [
                {"leave_name": "年休假", "unit": "day", "remain": 4,
                 "effective_year": "2026", "total": 5, "used": 1}]}

    provider = GaiaEmployeeDataProvider(FakeGaia())
    r = provider.annual_profile("EMP-001")
    assert r.data["annual_leave"]["mode"] == "flat"
    assert r.data["annual_leave"]["quota"] == 5
