"""假期余额 / 可申请假期类型查询工具。响应字段与旧工作流解析代码一致。"""
from hr_agent.schemas.tool_result import ok, err
from hr_agent.tools.gaia.client import from_state


def get_leave_balance(leave_type: str, tool_context) -> dict:
    """查询员工假期余额。

    Args:
        leave_type: 假期类型名称（如"年休假"）；传空字符串返回全部假期余额。
    """
    state = tool_context.state
    try:
        client = from_state(state)
        body = client.request(
            "prod", "POST",
            f"/wfm4integration-wfm4appapi/api/v1/gaiastandard/getemployeeleaveremaindata/{state['corp_id']}",
            json_body={"size": 10, "unitCode": "0", "employeeId": state["employeeId"],
                       "page": 1, "isIncludeSubUnit": False, "startDate": "", "endDate": ""})
        detail = body["details"]["employeeData"][0]["employeeDetailData"]
    except Exception as e:
        return err("gaia_error", f"查询假期余额失败：{e}")
    items = [{"leave_name": d.get("leaveName"), "effective_year": d.get("effectiveYear"),
              "total": d.get("leaveTotal", 0), "used": d.get("leaveUsed", 0),
              "remain": d.get("leaveRemain", 0)} for d in detail]
    if leave_type:
        items = [i for i in items if i["leave_name"] == leave_type]
    return ok(items)


def get_leave_permissions(tool_context) -> dict:
    """查询员工可申请的假期类型列表（假期权限）。"""
    state = tool_context.state
    try:
        client = from_state(state)
        body = client.request(
            "sandbox", "POST",
            f"/atd-webapi/api/gaiaStandard/leave/getEmployeeCanApplyLeaveType/{state['corp_id']}",
            json_body={"empId": state["employeeId"]}, tenant=state["corp_id"])
        if not body.get("result"):
            return err("gaia_error", f"查询假期权限失败：{body.get('message')}")
        data = [{"leave_code": x["LeaveCode"], "leave_type": x["LeaveType"]}
                for x in body.get("data", [])]
    except Exception as e:
        return err("gaia_error", f"查询假期权限失败：{e}")
    return ok(data)
