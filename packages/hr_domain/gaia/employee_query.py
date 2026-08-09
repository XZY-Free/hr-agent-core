"""医疗期 / 员工在职信息查询工具。请求/响应字段与《接口适配清单.md》§4 §5 一致。"""
from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.gaia.client import from_state


def get_medical_period(tool_context) -> dict:
    """查询员工医疗期余额（quota/used/balance）。"""
    state = tool_context.state
    try:
        client = from_state(state)
        body = client.request(
            "prod", "GET",
            "/wfm4-snowbeer/api/v1/medical/period/info/get",
            params={"employeeId": state["employeeId"]},
            tenant=state["corp_id"])
        d = body["details"][0]
    except Exception as e:
        return err("gaia_error", f"查询医疗期失败：{e}")
    return ok({"quota": d.get("quota", 0), "used": d.get("used", 0),
               "balance": d.get("balance", 0)})


def get_employee_info(tool_context) -> dict:
    """查询员工在职信息：性别、参工/本单位工龄、参工纪念日。

    工龄来自 `socialService` 字符串形如 "6 年 4 月 0 天"，按空格 split 解析。
    参工纪念日来自 `socialServiceDate` 形如 "2019-11-03"。
    """
    state = tool_context.state
    try:
        client = from_state(state)
        body = client.request(
            "prod", "POST",
            f"/hrcc/api/v1/{state['corp_id']}/openapi/person/search-effective",
            json_body={"employeeIdList": [state["employeeId"]]},
            extra_headers={"gaiaLanguage": "ZH-CN"})
        d = body["details"][0]
    except Exception as e:
        return err("gaia_error", f"查询员工信息失败：{e}")

    parts = (d.get("socialService") or "").split()
    # parts 形如 ["6", "年", "4", "月", "0", "天"]
    year = parts[0] if len(parts) > 0 else "0"
    month = parts[2] if len(parts) > 2 else "0"
    day = parts[4] if len(parts) > 4 else "0"
    sdate = d.get("socialServiceDate") or ""
    # "2019-11-03" → hire_month="11", hire_day="03"
    hire_month, hire_day = "0", "0"
    if "-" in sdate:
        segs = sdate.split("-")
        if len(segs) == 3:
            hire_month, hire_day = segs[1], segs[2]
    return ok({
        "sex": d.get("sex", ""),
        "social_service_year": year,
        "social_service_month": month,
        "social_service_day": day,
        "hire_month": hire_month,
        "hire_day": hire_day,
    })
