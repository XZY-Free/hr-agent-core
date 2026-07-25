from types import SimpleNamespace

import pytest

from hr_agent.tools.gaia.submit import submit_leave

STATE = {"employeeId": "E001", "corp_id": "corp1",
         "client_secret": "sec", "grant_type": "client_credentials"}
CTX = SimpleNamespace(state=STATE)


def _ctx():
    return SimpleNamespace(state=dict(STATE))


def _permissions(types):
    return {"success": True, "data": [{"leave_code": "X", "leave_type": t} for t in types]}


def _info(sex="F"):
    return {"success": True, "data": {
        "sex": sex, "social_service_year": "6", "social_service_month": "0",
        "social_service_day": "0", "hire_month": "11", "hire_day": "03"}}


def _schedule(first_start="08:00", first_code="SCQY01", first_date="2026-07-28"):
    return {"success": True, "data": [
        {"shift_date": first_date, "shift_code": first_code, "shift_name": "班",
         "start_time": first_start, "end_time": "17:00"},
    ]}


def _balance(remain=5.0, name="年休假"):
    return {"success": True, "data": [{"leave_name": name, "remain": remain,
                                       "total": 5, "used": 0, "effective_year": "2026"}]}


def _mock_all(monkeypatch, *, perms=None, info=None, sched=None, bal=None,
              perms_types=None, sex="F", first_start="08:00", first_code="SCQY01",
              first_date="2026-07-28", remain=5.0, balance_name="年休假"):
    if perms is None:
        perms = _permissions(perms_types or ["年休假"])
    if info is None:
        info = _info(sex)
    if sched is None:
        sched = _schedule(first_start, first_code, first_date)
    if bal is None:
        bal = _balance(remain, balance_name)
    monkeypatch.setattr("hr_agent.tools.gaia.submit.get_leave_permissions",
                        lambda ctx: perms)
    monkeypatch.setattr("hr_agent.tools.gaia.submit.get_employee_info",
                        lambda ctx: info)
    monkeypatch.setattr("hr_agent.tools.gaia.submit.get_schedule",
                        lambda sd, ed, ctx: sched)
    monkeypatch.setattr("hr_agent.tools.gaia.submit.get_leave_balance",
                        lambda t, ctx: bal)


def _common_args(**kw):
    base = dict(type_name="年休假", start_date="2026-07-28", end_date="2026-07-28",
                start_time="08:00", end_time="17:00", leave_days=1.0, reasons="家事")
    base.update(kw)
    return base


def test_no_permission(monkeypatch):
    _mock_all(monkeypatch, perms_types=["事假"])  # 年休假不在权限列表
    r = submit_leave(**_common_args(), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "no_permission"


def test_gender_mismatch(monkeypatch):
    # 女性员工申请陪产假（限男）
    _mock_all(monkeypatch, perms_types=["陪产假"], sex="F")
    r = submit_leave(**_common_args(type_name="陪产假"), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "gender_mismatch"


def test_rest_day(monkeypatch):
    # 首班 start_time == "00:00" 视为休息日
    _mock_all(monkeypatch, first_start="00:00", first_code="OFF01")
    r = submit_leave(**_common_args(), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "rest_day"


def test_not_scheduled(monkeypatch):
    # 排班返回空 → 未排班
    _mock_all(monkeypatch, sched={"success": True, "data": []})
    r = submit_leave(**_common_args(), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "not_scheduled"


def test_insufficient_balance(monkeypatch):
    _mock_all(monkeypatch, remain=0.5)  # 余额 0.5 < 请 1.0
    r = submit_leave(**_common_args(leave_days=1.0), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "insufficient_balance"


def test_invalid_days_not_half_multiple(monkeypatch):
    _mock_all(monkeypatch, remain=5.0)
    r = submit_leave(**_common_args(leave_days=0.3), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "invalid_days"


def test_invalid_days_zero(monkeypatch):
    _mock_all(monkeypatch, remain=5.0)
    r = submit_leave(**_common_args(leave_days=0.0), tool_context=_ctx())
    assert not r["success"] and r["error_type"] == "invalid_days"


def test_dry_run_success(monkeypatch):
    _mock_all(monkeypatch, remain=5.0)
    r = submit_leave(**_common_args(), tool_context=_ctx())
    assert r["success"]
    assert r["data"]["dry_run"] is True
    assert r["data"]["submitted"] is False
    payload = r["data"]["form"]
    assert payload["typeCode"] == "A31"
    assert payload["typeName"] == "年休假"
    assert payload["leaveDays"] == 1.0


def test_cross_day_end_date_plus_one(monkeypatch):
    # 19:00 → 07:00 跨天，end_date 应 +1
    _mock_all(monkeypatch, remain=5.0, first_start="19:00")
    r = submit_leave(**_common_args(start_time="19:00", end_time="07:00",
                                    end_date="2026-07-28"), tool_context=_ctx())
    assert r["success"]
    assert r["data"]["form"]["endDate"] == "2026-07-29"
    assert r["data"]["form"]["endTime"] == "07:00"


def test_dry_run_disabled_calls_real_submit_not_implemented(monkeypatch):
    _mock_all(monkeypatch, remain=5.0)
    monkeypatch.setenv("GAIA_DRY_RUN", "false")
    with pytest.raises(NotImplementedError):
        submit_leave(**_common_args(), tool_context=_ctx())
