"""Employee Data提供者的Stub标记和服务端凭据边界。"""

from apps.employee_data_agent.provider import (
    GaiaEmployeeDataProvider,
    GaiaServerConfig,
    StubEmployeeDataProvider,
)


def test_stub_source_is_explicit_for_success_not_found_and_failure():
    provider = StubEmployeeDataProvider({
        "EMP-001": {
            "annual_leave": {"mode": "flat", "quota": 5, "balance": []},
            "employment": {"social_service_year": "6"},
        },
        "EMP-AUTH": {"annual_error": "gaia_auth_failed"},
    })
    assert provider.annual_profile("EMP-001").source == "stub"
    assert provider.annual_profile("EMP-404").source == "stub"
    assert provider.annual_profile("EMP-AUTH").source == "stub"


def test_gaia_credentials_stay_out_of_tool_result(monkeypatch):
    """凭据只经共享 GaiaProvider 访问，绝不进入 ToolResult。

    WP-01：provider 不再伪造 session state，直接通过共享 GaiaProvider 读取数据。
    """
    captured = {"corp": None, "secret": None}

    class FakeGaia:
        def employee_info(self, employee_id):
            return {"success": True, "data": {
                "social_service_year": "6", "social_service_month": "0",
                "social_service_day": "0", "hire_month": "11", "hire_day": "03",
            }}

        def leave_balance(self, leave_type, employee_id):
            return {"success": True, "data": [{
                "leave_name": "年休假", "remain": 4, "total": 5, "used": 1,
                "effective_year": "2026",
            }]}

    provider = GaiaEmployeeDataProvider(FakeGaia())

    result = provider.annual_profile("EMP-001").to_tool_result()

    assert result["success"] is True
    assert result["source"] == "gaia"
    assert "client-secret" not in str(result)
    assert "corp-secret" not in str(result)
    assert "EMP-001" not in str(result)
    assert result["data"]["annual_leave"]["mode"] == "flat"
    assert result["data"]["annual_leave"]["quota"] == 5
