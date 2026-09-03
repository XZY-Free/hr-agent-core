"""Employee Data只读数据提供者；凭据不进入Agent会话。"""

import json
import os
from dataclasses import dataclass
from typing import Protocol

from packages.hr_domain.gaia.config import (
    gaia_server_config_from_env,
)
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.rules.annual_leave import compute_annual_leave


@dataclass(frozen=True)
class ProviderResponse:
    data: dict | None = None
    source: str | None = None
    partial: bool = False
    error_code: str | None = None

    def to_tool_result(self) -> dict:
        if self.error_code:
            return {
                "success": False,
                "error_type": self.error_code,
                "message": "本人数据暂时无法查询，请稍后重试。",
                "source": self.source,
            }
        return {
            "success": True,
            "data": self.data or {},
            "source": self.source,
            "partial": self.partial,
        }


class EmployeeDataProvider(Protocol):
    def leave_balances(self, employee_id: str, leave_type: str | None = None) -> ProviderResponse: ...
    def annual_profile(self, employee_id: str) -> ProviderResponse: ...
    def medical_period(self, employee_id: str) -> ProviderResponse: ...


class StubEmployeeDataProvider:
    """显式测试/本地Stub；不会静默替代Gaia。"""

    def __init__(self, records: dict[str, dict]):
        self.records = records

    def annual_profile(self, employee_id: str) -> ProviderResponse:
        record = self.records.get(employee_id)
        if not record:
            return ProviderResponse(source="stub", error_code="employee_not_found")
        override = record.get("annual_error")
        if override:
            return ProviderResponse(source="stub", error_code=override)
        return ProviderResponse(
            data={
                "annual_leave": record.get("annual_leave", {}),
                "employment": record.get("employment", {}),
            },
            source="stub",
            partial=bool(record.get("partial")),
        )

    def medical_period(self, employee_id: str) -> ProviderResponse:
        record = self.records.get(employee_id)
        if not record:
            return ProviderResponse(source="stub", error_code="employee_not_found")
        override = record.get("medical_error")
        if override:
            return ProviderResponse(source="stub", error_code=override)
        return ProviderResponse(
            data={"medical_period": record.get("medical_period", {})},
            source="stub",
            partial=bool(record.get("medical_partial")),
        )

    def leave_balances(self, employee_id: str, leave_type: str | None = None) -> ProviderResponse:
        record = self.records.get(employee_id)
        if not record:
            return ProviderResponse(source="stub", error_code="employee_not_found")
        override = record.get("leave_error")
        if override:
            return ProviderResponse(source="stub", error_code=override)
        rows = list(record.get("leave_balances", []))
        if leave_type:
            rows = [r for r in rows if r.get("leave_name") == leave_type]
        return ProviderResponse(
            data={"leave_balances": rows},
            source="stub",
            partial=bool(record.get("leave_partial")),
        )

    @classmethod
    def from_env(cls) -> "StubEmployeeDataProvider":
        raw = os.getenv("EMPLOYEE_DATA_STUB_JSON", "")
        try:
            records = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise RuntimeError("Employee Data Stub配置无效") from None
        if not isinstance(records, dict) or not records:
            raise RuntimeError("Employee Data Stub配置无效")
        return cls(records)


@dataclass(frozen=True)
class GaiaServerConfig:
    """兼容别名：正式定义在 packages.hr_domain.gaia.config。"""

    corp_id: str
    client_secret: str
    grant_type: str

    def to_shared(self):
        from packages.hr_domain.gaia.config import GaiaServerConfig as Shared

        return Shared(
            corp_id=self.corp_id,
            client_secret=self.client_secret,
            grant_type=self.grant_type,
            schedule_tenant=os.getenv("GAIA_SCHEDULE_TENANT", "").strip(),
        )


class GaiaEmployeeDataProvider:
    """通过共享 GaiaProvider 读取当前员工数据；不伪造 session state。"""

    def __init__(self, provider: GaiaProvider):
        self._gaia = provider

    @staticmethod
    def _error(result: dict) -> ProviderResponse:
        text = str(result.get("message", "")).lower()
        if any(word in text for word in ("jwt", "认证", "unauthorized", "forbidden")):
            code = "gaia_auth_failed"
        elif any(word in text for word in ("不存在", "not found")):
            code = "employee_not_found"
        else:
            code = "gaia_unavailable"
        return ProviderResponse(source="gaia", error_code=code)

    def annual_profile(self, employee_id: str) -> ProviderResponse:
        info = self._gaia.employee_info(employee_id)
        if not info.get("success"):
            return self._error(info)
        balance = self._gaia.leave_balance("年休假", employee_id)
        balance_data = balance.get("data") if balance.get("success") else None
        if not balance.get("success"):
            return self._error(balance)
        from datetime import date

        annual = compute_annual_leave(info["data"], balance_data, date.today())
        return ProviderResponse(
            data={"annual_leave": annual, "employment": info["data"]},
            source="gaia",
            partial=annual.get("balance") is None,
        )

    def medical_period(self, employee_id: str) -> ProviderResponse:
        result = self._gaia.medical_period(employee_id)
        if not result.get("success"):
            return self._error(result)
        return ProviderResponse(
            data={"medical_period": result["data"]},
            source="gaia",
        )

    def leave_balances(self, employee_id: str, leave_type: str | None = None) -> ProviderResponse:
        result = self._gaia.leave_balance(leave_type or "", employee_id)
        if not result.get("success"):
            return self._error(result)
        return ProviderResponse(
            data={"leave_balances": result["data"]},
            source="gaia",
        )


def provider_from_env() -> EmployeeDataProvider:
    backend = os.getenv("EMPLOYEE_DATA_BACKEND", "gaia").strip().lower()
    if backend == "stub":
        return StubEmployeeDataProvider.from_env()
    if backend != "gaia":
        raise RuntimeError("EMPLOYEE_DATA_BACKEND仅支持gaia或stub")
    config = gaia_server_config_from_env()
    return GaiaEmployeeDataProvider(GaiaProvider(
        config=config,
        backend=os.getenv("GAIA_BACKEND", "gaia").strip().lower(),
    ))
