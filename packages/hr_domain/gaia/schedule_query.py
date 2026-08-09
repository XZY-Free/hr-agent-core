"""排班查询工具。沙箱环境，tenant 固定 snowbeertest（按《接口适配清单.md》§6）。"""
from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.gaia.client import from_state


def get_schedule(start_date: str, end_date: str, tool_context) -> dict:
    """查询员工排班数据。

    Args:
        start_date: 起始日期 yyyy-MM-dd
        end_date: 结束日期 yyyy-MM-dd
    """
    state = tool_context.state
    try:
        client = from_state(state)
        body = client.request(
            "sandbox", "POST",
            "/wfm4customization/api/v1/scheduling/attendance/getScheduleData",
            json_body={"size": "30", "startDate": start_date, "endDate": end_date,
                       "unitCode": "", "employeeId": state["employeeId"],
                       "page": "1", "isIncludeSubUnit": False},
            tenant="snowbeertest")
        detail = body["details"]["employeeData"][0]["employeeDetailData"]
    except Exception as e:
        return err("gaia_error", f"查询排班失败：{e}")
    items = [{"shift_date": d.get("shiftDate"), "shift_code": d.get("shiftCode"),
              "shift_name": d.get("shiftName"), "start_time": d.get("startTime"),
              "end_time": d.get("endTime")} for d in detail]
    return ok(items)
