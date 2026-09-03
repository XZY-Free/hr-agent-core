import responses
from types import SimpleNamespace

from packages.hr_domain.gaia.client import BASE_URLS
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.gaia.employee_query import get_medical_period, get_employee_info
from packages.hr_domain.execution.context import (
    HREXecutionContext,
    bind_hr_execution_context,
)
from packages.hr_domain.identity import TrustedIdentityResolver

STATE = {"employeeId": "E001", "corp_id": "corp1",
         "client_secret": "sec", "grant_type": "client_credentials"}
CTX = SimpleNamespace(state=STATE)

MEDICAL_RESP = {"details": [{"quota": 24, "used": 3, "balance": 21}]}
PERSON_RESP = {"details": [{"sex": "F", "socialService": "6 年 4 月 0 天",
                            "socialServiceDate": "2019-11-03"}]}


def _mock_oauth(env):
    responses.post(f"{BASE_URLS[env]}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "j"})


def _config():
    return GaiaServerConfig(
        corp_id="corp1", client_secret="sec", grant_type="client_credentials",
        schedule_tenant="snowbeertest",
    )


def _bind_context(user_id="user-alpha"):
    config = _config()
    ctx = HREXecutionContext(
        internal_user_id=user_id,
        identity_resolver=TrustedIdentityResolver(
            {"user-alpha": "E001"}, ref_secret="unit-secret"),
        gaia_config=config,
        gaia_provider=GaiaProvider(config),
        request_id="req-a",
        context_id="ctx-a",
    )
    return bind_hr_execution_context(ctx)


@responses.activate
def test_get_medical_period():
    _mock_oauth("prod")
    responses.get(f"{BASE_URLS['prod']}/wfm4-snowbeer/api/v1/medical/period/info/get",
                  json=MEDICAL_RESP)
    with _bind_context():
        r = get_medical_period(CTX)
    assert r["success"] and r["data"] == {"quota": 24, "used": 3, "balance": 21}
    # 验证 query 参数与 tenant 头
    req = responses.calls[1].request
    assert "employeeId=E001" in req.url
    assert req.headers["tenant"] == "corp1"


@responses.activate
def test_get_medical_period_gaia_error():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": False, "code": 500, "message": "down"})
    with _bind_context():
        r = get_medical_period(CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"


@responses.activate
def test_get_employee_info_parses_social_service():
    _mock_oauth("prod")
    responses.post(f"{BASE_URLS['prod']}/hrcc/api/v1/corp1/openapi/person/search-effective",
                   json=PERSON_RESP)
    with _bind_context():
        r = get_employee_info(CTX)
    assert r["success"]
    d = r["data"]
    assert d["sex"] == "F"
    assert d["social_service_year"] == "6"
    assert d["social_service_month"] == "4"
    assert d["social_service_day"] == "0"
    assert d["hire_month"] == "11"
    assert d["hire_day"] == "03"
    # gaiaLanguage 头存在
    req = responses.calls[1].request
    assert req.headers["gaiaLanguage"] == "ZH-CN"


@responses.activate
def test_get_employee_info_gaia_error():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": False, "code": 500, "message": "down"})
    with _bind_context():
        r = get_employee_info(CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"


def test_medical_period_identity_unverified_without_binding():
    r = get_medical_period(CTX)
    assert not r["success"] and r["error_type"] == "identity_unverified"


def test_employee_info_identity_unverified_when_unmapped():
    with _bind_context(user_id="unknown-user"):
        r = get_employee_info(CTX)
    assert not r["success"] and r["error_type"] == "identity_unverified"
