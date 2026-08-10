"""Employee Data只读数据提供者；凭据不进入Agent会话。"""

import json
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Protocol

from packages.hr_domain.gaia.employee_query import get_employee_info
from packages.hr_domain.gaia.employee_query import get_medical_period as gaia_medical_period
from packages.hr_domain.rules.annual_leave import calc_annual_leave as gaia_annual_leave


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
    corp_id: str
    client_secret: str
    grant_type: str


class GaiaEmployeeDataProvider:
    """通过现有确定性Gaia工具读取当前员工数据。"""

    def __init__(self, config: GaiaServerConfig):
        self.config = config

    def _context(self, employee_id: str):
        return SimpleNamespace(state={
            "employeeId": employee_id,
            "corp_id": self.config.corp_id,
            "client_secret": self.config.client_secret,
            "grant_type": self.config.grant_type,
        })

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
        context = self._context(employee_id)
        info = get_employee_info(context)
        if not info.get("success"):
            return self._error(info)
        annual = gaia_annual_leave(context)
        if not annual.get("success"):
            return self._error(annual)
        return ProviderResponse(
            data={"annual_leave": annual["data"], "employment": info["data"]},
            source="gaia",
            partial=annual["data"].get("balance") is None,
        )

    def medical_period(self, employee_id: str) -> ProviderResponse:
        result = gaia_medical_period(self._context(employee_id))
        if not result.get("success"):
            return self._error(result)
        return ProviderResponse(
            data={"medical_period": result["data"]},
            source="gaia",
        )


def provider_from_env() -> EmployeeDataProvider:
    backend = os.getenv("EMPLOYEE_DATA_BACKEND", "gaia").strip().lower()
    if backend == "stub":
        return StubEmployeeDataProvider.from_env()
    if backend != "gaia":
        raise RuntimeError("EMPLOYEE_DATA_BACKEND仅支持gaia或stub")
    values = {
        "corp_id": os.getenv("GAIA_CORP_ID", "").strip(),
        "client_secret": os.getenv("GAIA_CLIENT_SECRET", "").strip(),
        "grant_type": os.getenv("GAIA_GRANT_TYPE", "").strip(),
    }
    if not all(values.values()):
        raise RuntimeError("Employee Data Gaia服务端配置缺失")
    return GaiaEmployeeDataProvider(GaiaServerConfig(**values))
