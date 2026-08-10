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


def test_gaia_credentials_stay_in_ephemeral_internal_context(monkeypatch):
    captured = []

    def fake_info(context):
        captured.append(dict(context.state))
        return {"success": True, "data": {
            "social_service_year": "6", "social_service_month": "0",
            "social_service_day": "0", "hire_month": "11", "hire_day": "03",
        }}

    def fake_annual(context):
        captured.append(dict(context.state))
        return {"success": True, "data": {
            "mode": "flat", "quota": 5, "balance": [],
        }}

    monkeypatch.setattr("apps.employee_data_agent.provider.get_employee_info", fake_info)
    monkeypatch.setattr("apps.employee_data_agent.provider.gaia_annual_leave", fake_annual)
    provider = GaiaEmployeeDataProvider(GaiaServerConfig(
        corp_id="corp-secret",
        client_secret="client-secret",
        grant_type="client_credentials",
    ))

    result = provider.annual_profile("EMP-001").to_tool_result()

    assert result["success"] is True
    assert result["source"] == "gaia"
    assert "client-secret" not in str(result)
    assert "corp-secret" not in str(result)
    assert captured and captured[0]["employeeId"] == "EMP-001"
