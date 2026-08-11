"""盖亚 OpenAPI 客户端：JWT 缓存、统一请求封装。地址与环境按《接口适配清单.md》原样。"""
import json
import os
import time
from datetime import date, timedelta

import requests

BASE_URLS = {"prod": "https://openapi.gaiaworkforce.com",
             "sandbox": "https://openapi-s.gaiaworkforce.com"}
JWT_TTL_SECONDS = 25 * 60   # 无法解析 exp 时的保守缓存时长
TIMEOUT = 30                # 与旧工作流一致


class GaiaClient:
    def __init__(self, corp_id: str, client_secret: str, grant_type: str):
        self.corp_id = corp_id
        self.client_secret = client_secret
        self.grant_type = grant_type
        self._jwt_cache: dict[str, tuple[str, float]] = {}   # env -> (jwt, expire_ts)

    def get_jwt(self, env: str) -> str:
        cached = self._jwt_cache.get(env)
        if cached and cached[1] > time.time():
            return cached[0]
        resp = requests.post(
            f"{BASE_URLS[env]}/identity/api/v1/oauth",
            data={"grant_type": self.grant_type, "corp_id": self.corp_id,
                  "client_secret": self.client_secret},
            timeout=TIMEOUT)
        body = resp.json()
        if not (body.get("result") and body.get("code") == 200):
            raise RuntimeError(f"获取盖亚JWT失败: {body.get('message')}")
        jwt = body["data"]
        self._jwt_cache[env] = (jwt, time.time() + JWT_TTL_SECONDS)
        return jwt

    def request(self, env: str, method: str, path: str, *, json_body=None,
                params=None, extra_headers=None, tenant: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.get_jwt(env)}"}
        if tenant:
            headers["tenant"] = tenant
        if extra_headers:
            headers.update(extra_headers)
        resp = requests.request(method, f"{BASE_URLS[env]}{path}",
                                json=json_body, params=params,
                                headers=headers, timeout=TIMEOUT)
        return resp.json()


class ConfiguredGaiaStubClient:
    """Explicit development-only Gaia read stub; never a fallback."""

    def __init__(self, config: dict):
        required = {
            "leave_balance",
            "permissions",
            "employee",
            "medical_period",
            "rest_day_offsets",
        }
        if not isinstance(config, dict) or not required <= set(config):
            raise RuntimeError("GAIA Stub配置无效")
        if not isinstance(config["leave_balance"], list):
            raise RuntimeError("GAIA Stub配置无效")
        if not isinstance(config["permissions"], list):
            raise RuntimeError("GAIA Stub配置无效")
        if not isinstance(config["employee"], dict):
            raise RuntimeError("GAIA Stub配置无效")
        if not isinstance(config["medical_period"], dict):
            raise RuntimeError("GAIA Stub配置无效")
        if not all(isinstance(value, int) for value in config["rest_day_offsets"]):
            raise RuntimeError("GAIA Stub配置无效")
        self.config = config

    @classmethod
    def from_env(cls) -> "ConfiguredGaiaStubClient":
        if os.getenv("GAIA_DRY_RUN", "true").lower() not in {"true", "1", "yes"}:
            raise RuntimeError("GAIA Stub只允许用于干跑开发环境")
        try:
            config = json.loads(os.getenv("GAIA_STUB_JSON", ""))
        except (TypeError, json.JSONDecodeError):
            raise RuntimeError("GAIA Stub配置无效") from None
        return cls(config)

    def request(
        self,
        env: str,
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        extra_headers=None,
        tenant: str | None = None,
    ) -> dict:
        if "getemployeeleaveremaindata" in path:
            return {"code": 200, "details": {"employeeData": [{
                "employeeDetailData": self.config["leave_balance"],
            }]}}
        if "getEmployeeCanApplyLeaveType" in path:
            return {"result": True, "data": self.config["permissions"]}
        if "medical/period/info/get" in path:
            return {"details": [self.config["medical_period"]]}
        if "person/search-effective" in path:
            return {"details": [self.config["employee"]]}
        if "getScheduleData" in path:
            return self._schedule(json_body or {})
        raise RuntimeError("GAIA Stub不支持该读取接口")

    def _schedule(self, body: dict) -> dict:
        try:
            start = date.fromisoformat(body["startDate"])
            end = date.fromisoformat(body.get("endDate") or body["startDate"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("GAIA Stub排班日期无效") from None
        rest_dates = {
            date.today() + timedelta(days=offset)
            for offset in self.config["rest_day_offsets"]
        }
        rows = []
        current = start
        while current <= end:
            rest = current in rest_dates
            rows.append({
                "shiftDate": current.isoformat(),
                "shiftCode": "OFF01" if rest else "SCQY01",
                "shiftName": "休息" if rest else "白班",
                "startTime": "00:00" if rest else "08:00",
                "endTime": "00:00" if rest else "17:00",
            })
            current += timedelta(days=1)
        return {"details": {"employeeData": [{"employeeDetailData": rows}]}}


def from_state(state) -> GaiaClient | ConfiguredGaiaStubClient:
    """从 ADK session state 构造客户端（业务变量由调用方注入 state）。"""
    backend = os.getenv("GAIA_BACKEND", "gaia").strip().lower()
    if backend == "stub":
        return ConfiguredGaiaStubClient.from_env()
    if backend != "gaia":
        raise RuntimeError("GAIA_BACKEND仅支持gaia或stub")
    return GaiaClient(corp_id=state["corp_id"],
                      client_secret=state["client_secret"],
                      grant_type=state["grant_type"])
