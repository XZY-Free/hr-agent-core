from hr_agent.schemas.tool_result import ok, err
from hr_agent.schemas.leave_form import LeaveForm


def test_ok_err_shape():
    assert ok({"a": 1}) == {"success": True, "data": {"a": 1}}
    e = err("gaia_error", "接口失败")
    assert e == {"success": False, "error_type": "gaia_error", "message": "接口失败"}


def test_leave_form_payload():
    f = LeaveForm(type_name="年休假", start_date="2026-07-28", end_date="2026-07-28",
                  start_time="08:00", end_time="17:00", leave_days=1.0, reasons="家中有事")
    p = f.to_submit_payload()
    assert p["typeCode"] == "A31" and p["typeName"] == "年休假"
    assert p["startDate"] == "2026-07-28" and p["leaveDays"] == 1.0
    assert p["startTime"] == "08:00" and p["endTime"] == "17:00"
    assert p["endDate"] == "2026-07-28" and p["reasons"] == "家中有事"


def test_leave_form_unknown_type_empty_code():
    f = LeaveForm(type_name="神秘假", start_date="2026-07-28", end_date="2026-07-28",
                  start_time="08:00", end_time="17:00", leave_days=1.0)
    assert f.to_submit_payload()["typeCode"] == ""
