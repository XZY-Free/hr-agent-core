"""共享 Gaia Provider — 领域数据访问的唯一入口。

调用者只提供业务参数（员工身份、日期、假期类型），不提供 corp_id / secret /
grant_type / tenant。客户端由共享 GaiaServerConfig 在服务端构造；stub 只能显式
开启。所有方法返回与旧 gaia 工具一致的 ok/err 结构，供领域规则与 Agent 工具复用。
"""

import os
from typing import Literal

from packages.hr_domain.gaia.client import (
    ConfiguredGaiaStubClient,
    GaiaClient,
)
from packages.hr_domain.gaia.config import GaiaServerConfig

Env = Literal["prod", "sandbox"]


class GaiaProvider:
    def __init__(self, config: GaiaServerConfig, *, backend: str | None = None):
        self.config = config
        self._backend = (
            backend or os.getenv("GAIA_BACKEND", "gaia").strip().lower()
        )
        if self._backend not in {"gaia", "stub"}:
            raise RuntimeError("GAIA_BACKEND仅支持gaia或stub")
        self._stub_client: ConfiguredGaiaStubClient | None = None

    def _client(self, env: Env):
        if self._backend == "stub":
            if self._stub_client is None:
                self._stub_client = ConfiguredGaiaStubClient.from_env()
            return self._stub_client
        return GaiaClient(
            corp_id=self.config.corp_id,
            client_secret=self.config.client_secret,
            grant_type=self.config.grant_type,
        )

    def employee_info(self, employee_id: str) -> dict:
        try:
            client = self._client("prod")
            body = client.request(
                "prod", "POST",
                f"/hrcc/api/v1/{self.config.corp_id}/openapi/person/search-effective",
                json_body={"employeeIdList": [employee_id]},
                extra_headers={"gaiaLanguage": "ZH-CN"})
            d = body["details"][0]
        except Exception:
            return _err("当前无法查询员工信息，请联系管理员检查服务配置。")
        parts = (d.get("socialService") or "").split()
        year = parts[0] if len(parts) > 0 else "0"
        month = parts[2] if len(parts) > 2 else "0"
        day = parts[4] if len(parts) > 4 else "0"
        sdate = d.get("socialServiceDate") or ""
        hire_month, hire_day = "0", "0"
        if "-" in sdate:
            segs = sdate.split("-")
            if len(segs) == 3:
                hire_month, hire_day = segs[1], segs[2]
        return _ok({
            "sex": d.get("sex", ""),
            "social_service_year": year,
            "social_service_month": month,
            "social_service_day": day,
            "hire_month": hire_month,
            "hire_day": hire_day,
        })

    def medical_period(self, employee_id: str) -> dict:
        try:
            client = self._client("prod")
            body = client.request(
                "prod", "GET",
                "/wfm4-snowbeer/api/v1/medical/period/info/get",
                params={"employeeId": employee_id},
                tenant=self.config.corp_id)
            d = body["details"][0]
        except Exception:
            return _err("当前无法查询医疗期，请联系管理员检查服务配置。")
        return _ok({"quota": d.get("quota", 0), "used": d.get("used", 0),
                    "balance": d.get("balance", 0)})

    def leave_balance(self, leave_type: str, employee_id: str) -> dict:
        try:
            client = self._client("prod")
            body = client.request(
                "prod", "POST",
                f"/wfm4integration-wfm4appapi/api/v1/gaiastandard/getemployeeleaveremaindata/{self.config.corp_id}",
                json_body={"size": 10, "unitCode": "0", "employeeId": employee_id,
                           "page": 1, "isIncludeSubUnit": False,
                           "startDate": "", "endDate": ""})
            detail = body["details"]["employeeData"][0]["employeeDetailData"]
        except Exception:
            return _err("当前无法查询假期余额，请联系管理员检查服务配置。")
        items = [_normalize_balance_row(d) for d in detail]
        if leave_type:
            items = [i for i in items if i["leave_name"] == leave_type]
        return _ok(items)

    def leave_permissions(self, employee_id: str) -> dict:
        try:
            client = self._client("sandbox")
            body = client.request(
                "sandbox", "POST",
                f"/atd-webapi/api/gaiaStandard/leave/getEmployeeCanApplyLeaveType/{self.config.corp_id}",
                json_body={"empId": employee_id}, tenant=self.config.corp_id)
            if not body.get("result"):
                return _err("当前无法查询假期权限，请联系管理员检查服务配置。")
            data = [{"leave_code": x["LeaveCode"], "leave_type": x["LeaveType"]}
                    for x in body.get("data", [])]
        except Exception:
            return _err("当前无法查询假期权限，请联系管理员检查服务配置。")
        return _ok(data)

    def schedule(self, start_date: str, end_date: str, employee_id: str) -> dict:
        try:
            client = self._client("sandbox")
            body = client.request(
                "sandbox", "POST",
                "/wfm4customization/api/v1/scheduling/attendance/getScheduleData",
                json_body={"size": "30", "startDate": start_date, "endDate": end_date,
                           "unitCode": "", "employeeId": employee_id,
                           "page": "1", "isIncludeSubUnit": False},
                tenant=self.config.schedule_tenant)
            detail = body["details"]["employeeData"][0]["employeeDetailData"]
        except Exception:
            return _err("当前无法查询排班，请联系管理员检查服务配置。")
        items = [{
            "shift_date": d.get("shiftDate"),
            "shift_code": d.get("shiftCode"),
            "shift_name": d.get("shiftName"),
            "start_time": d.get("startTime"),
            "end_time": d.get("endTime"),
            # 半天边界原始字段（Gaia 有则保留，无则 None；不得由模型/规则定中点）。
            "meal_begin_time": d.get("mealBeginTime"),
            "meal_end_time": d.get("mealEndTime"),
            "middle_time": d.get("middleTime"),
        } for d in detail]
        return _ok(items)

    def raw_client(self, env: Env) -> GaiaClient | ConfiguredGaiaStubClient:
        """提交等需要原生 client 的场景；凭据仍来自服务端 config。"""
        return self._client(env)  # type: ignore[return-value]


def _ok(data) -> dict:
    return {"success": True, "data": data}


def _err(message: str) -> dict:
    return {"success": False, "error_type": "gaia_error", "message": message}


def _normalize_balance_row(d: dict) -> dict:
    """标准化单条假期余额，保留 unit 与 freeze/approving 事实。

    WP-03 §5：不能只留数字。leaveUnit 归一为 day / hour；未知单位保留原始值，
    不静默按天。freeze/approving 字段保留，供"余额与可用额度不一致"解释。
    """
    unit = _normalize_unit(d.get("leaveUnit"))
    return {
        "leave_code": d.get("leaveCode"),
        "leave_name": d.get("leaveName"),
        "effective_year": d.get("effectiveYear"),
        "unit": unit,
        "total": d.get("leaveTotal", 0),
        "used": d.get("leaveUsed", 0),
        "remain": d.get("leaveRemain", 0),
        "approving": d.get("leaveApproving", 0),
        "freeze": d.get("freeze", 0),
    }


def _normalize_unit(unit: str | None) -> str:
    if not unit:
        return "day"
    normalized = str(unit).strip().lower()
    if normalized in {"day", "d", "天", "1"}:
        return "day"
    if normalized in {"hour", "h", "时", "小时", "2"}:
        return "hour"
    return normalized
