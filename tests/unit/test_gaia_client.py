import json
from datetime import date, timedelta

import pytest
import responses
from packages.hr_domain.gaia.client import (
    BASE_URLS,
    ConfiguredGaiaStubClient,
    GaiaClient,
    from_state,
)


def make_client():
    return GaiaClient(corp_id="corp1", client_secret="sec", grant_type="client_credentials")


@responses.activate
def test_jwt_cached_within_ttl():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "fake.jwt.token"})
    c = make_client()
    assert c.get_jwt("prod") == "fake.jwt.token"
    assert c.get_jwt("prod") == "fake.jwt.token"      # 第二次走缓存
    assert len(responses.calls) == 1                   # 只发了一次 oauth


@responses.activate
def test_jwt_cache_separated_per_env():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "prod.jwt"})
    responses.post(f"{BASE_URLS['sandbox']}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "sbx.jwt"})
    c = make_client()
    assert c.get_jwt("prod") == "prod.jwt"
    assert c.get_jwt("sandbox") == "sbx.jwt"
    assert c.get_jwt("prod") == "prod.jwt"  # 仍走缓存
    assert len(responses.calls) == 2


@responses.activate
def test_request_carries_bearer_and_tenant():
    responses.post(f"{BASE_URLS['sandbox']}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "sbx.jwt"})
    responses.post(f"{BASE_URLS['sandbox']}/some/api", json={"result": True})
    c = make_client()
    c.request("sandbox", "POST", "/some/api", json_body={}, tenant="corp1")
    req = responses.calls[1].request
    assert req.headers["Authorization"] == "Bearer sbx.jwt"
    assert req.headers["tenant"] == "corp1"


@responses.activate
def test_request_passes_params_and_extra_headers():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "j"})
    responses.get(f"{BASE_URLS['prod']}/p", json={"result": True})
    c = make_client()
    c.request("prod", "GET", "/p", params={"q": "1"},
              extra_headers={"gaiaLanguage": "ZH-CN"})
    req = responses.calls[1].request
    assert req.headers["gaiaLanguage"] == "ZH-CN"
    assert "q=1" in req.url


@responses.activate
def test_oauth_failure_raises_gaia_error():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": False, "code": 500, "message": "bad secret"})
    c = make_client()
    try:
        c.get_jwt("prod")
        assert False
    except RuntimeError as e:
        assert "bad secret" in str(e)


def test_from_state_factory():
    state = {"corp_id": "c", "client_secret": "s", "grant_type": "g"}
    c = from_state(state)
    assert c.corp_id == "c" and c.client_secret == "s" and c.grant_type == "g"


def test_from_state_uses_explicit_configured_stub_without_network(monkeypatch):
    monkeypatch.setenv("GAIA_BACKEND", "stub")
    monkeypatch.setenv("GAIA_DRY_RUN", "true")
    monkeypatch.setenv("GAIA_STUB_JSON", json.dumps({
        "leave_balance": [{
            "effectiveYear": "2026",
            "leaveCode": "A31",
            "leaveName": "年休假",
            "leaveUsed": 1,
            "leaveTotal": 5,
            "leaveRemain": 4,
        }],
        "permissions": [{"LeaveCode": "A31", "LeaveType": "年休假"}],
        "employee": {
            "sex": "F",
            "socialService": "6 年 4 月 0 天",
            "socialServiceDate": "2019-11-03",
        },
        "medical_period": {"quota": 24, "used": 3, "balance": 21},
        "rest_day_offsets": [-2],
    }))

    client = from_state({
        "corp_id": "fixture-corp",
        "client_secret": "fixture-secret",
        "grant_type": "client_credentials",
    })
    rest_day = (date.today() - timedelta(days=2)).isoformat()
    schedule = client.request(
        "sandbox",
        "POST",
        "/wfm4customization/api/v1/scheduling/attendance/getScheduleData",
        json_body={"startDate": rest_day, "endDate": rest_day},
    )

    assert isinstance(client, ConfiguredGaiaStubClient)
    row = schedule["details"]["employeeData"][0]["employeeDetailData"][0]
    assert row["shiftDate"] == rest_day
    assert row["startTime"] == "00:00"


def test_stub_backend_fails_closed_without_dry_run_or_valid_config(monkeypatch):
    monkeypatch.setenv("GAIA_BACKEND", "stub")
    monkeypatch.setenv("GAIA_DRY_RUN", "false")
    monkeypatch.setenv("GAIA_STUB_JSON", "{}")

    with pytest.raises(RuntimeError, match="GAIA Stub"):
        from_state({
            "corp_id": "fixture-corp",
            "client_secret": "fixture-secret",
            "grant_type": "client_credentials",
        })
