import datetime
from types import SimpleNamespace
import math

import pytest

from packages.hr_domain.rules.annual_leave import split_year_quota, calc_annual_leave


# ---------- split_year_quota 纯函数 ----------

def test_split_year_quota_regular_2025():
    # 11月3日（含当日）：daysBefore=307, daysAfter=58；2025 非闰年 total=365
    # before=floor(307/365*5*10)/10=floor(42.05)/10=4.2
    # after =floor(58/365*10*10)/10=floor(15.89)/10=1.5
    r = split_year_quota(11, 3, 2025)
    assert r["before"] == 4.2
    assert r["after"] == 1.5


def test_split_year_quota_leap_year_2024():
    # 2024 闰年 total=366；2月29日（含当日）：31+29=60 天 before，after=306
    # before=floor(60/366*5*10)/10=floor(8.196)/10=0.8
    # after =floor(306/366*10*10)/10=floor(83.606)/10=8.3
    r = split_year_quota(2, 29, 2024)
    assert r["before"] == 0.8
    assert r["after"] == 8.3


def test_split_year_quota_jan1_all_after():
    # 1月1日（含当日）=1 天 before，364 天 after（非闰年）
    # before=floor(1/365*5*10)/10=floor(0.136)/10=0.0
    # after =floor(364/365*10*10)/10=floor(99.72)/10=9.9
    r = split_year_quota(1, 1, 2025)
    assert r["before"] == 0.0
    assert r["after"] == 9.9


# ---------- calc_annual_leave ADK 工具 ----------

def _employee_info(years: str, m: str, d: str):
    return {"success": True, "data": {
        "sex": "F",
        "social_service_year": years, "social_service_month": "0", "social_service_day": "0",
        "hire_month": m, "hire_day": d,
    }}


def _balance(remain: float):
    return {"success": True, "data": [{"leave_name": "年休假", "remain": remain,
                                       "total": 5, "used": 5 - remain, "effective_year": "2026"}]}


def _ctx():
    return SimpleNamespace(state={"employeeId": "E001", "corp_id": "c",
                                  "client_secret": "s", "grant_type": "g"})


def _mock_today(monkeypatch, y, m, d):
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date(y, m, d)
    monkeypatch.setattr("packages.hr_domain.rules.annual_leave.date", FakeDate)


def _mock_tools(monkeypatch, info, balance):
    monkeypatch.setattr("packages.hr_domain.rules.annual_leave.get_employee_info",
                        lambda ctx: info)
    monkeypatch.setattr("packages.hr_domain.rules.annual_leave.get_leave_balance",
                        lambda t, ctx: balance)


def test_flat_under_10_years(monkeypatch):
    _mock_today(monkeypatch, 2026, 7, 25)  # 参工 2019-11-03，工龄 6
    _mock_tools(monkeypatch, _employee_info("6", "11", "03"), _balance(4))
    r = calc_annual_leave(_ctx())
    assert r["success"] and r["data"]["mode"] == "flat"
    assert r["data"]["quota"] == 5
    assert r["data"]["balance"][0]["remain"] == 4


def test_flat_over_10_years(monkeypatch):
    # 参工 2015-11-03，工龄 11，today=2027-07-25 → 满10年=2025，非跨档年
    _mock_today(monkeypatch, 2027, 7, 25)
    _mock_tools(monkeypatch, _employee_info("11", "11", "03"), _balance(0))
    r = calc_annual_leave(_ctx())
    assert r["success"] and r["data"]["mode"] == "flat"
    assert r["data"]["quota"] == 10


def test_split_at_10_year_boundary_before_anniversary(monkeypatch):
    # 参工 2019-11-03，工龄 9，today=2029-07-25 → 满10年=2029 跨档年，纪念日未过
    _mock_today(monkeypatch, 2029, 7, 25)
    _mock_tools(monkeypatch, _employee_info("9", "11", "03"), _balance(2))
    r = calc_annual_leave(_ctx())
    assert r["success"] and r["data"]["mode"] == "split"
    assert r["data"]["before"] == 4.2
    assert r["data"]["after"] == 1.5
    assert r["data"]["anniversary"] == "11-03"
    assert r["data"]["balance"][0]["remain"] == 2


def test_split_at_10_year_boundary_after_anniversary(monkeypatch):
    # 参工 2019-11-03，工龄 10，today=2029-12-01 → 满10年=2029 跨档年，纪念日已过
    _mock_today(monkeypatch, 2029, 12, 1)
    _mock_tools(monkeypatch, _employee_info("10", "11", "03"), _balance(2))
    r = calc_annual_leave(_ctx())
    assert r["success"] and r["data"]["mode"] == "split"
    assert r["data"]["anniversary"] == "11-03"


def test_calc_propagates_employee_info_error(monkeypatch):
    _mock_today(monkeypatch, 2026, 7, 25)
    err = {"success": False, "error_type": "gaia_error", "message": "down"}
    monkeypatch.setattr("packages.hr_domain.rules.annual_leave.get_employee_info",
                        lambda ctx: err)
    r = calc_annual_leave(_ctx())
    assert not r["success"] and r["error_type"] == "gaia_error"
