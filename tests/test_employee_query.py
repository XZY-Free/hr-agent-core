import responses
from types import SimpleNamespace
from hr_agent.tools.gaia.client import BASE_URLS
from hr_agent.tools.gaia.employee_query import get_medical_period, get_employee_info

STATE = {"employeeId": "E001", "corp_id": "corp1",
         "client_secret": "sec", "grant_type": "client_credentials"}
CTX = SimpleNamespace(state=STATE)

MEDICAL_RESP = {"details": [{"quota": 24, "used": 3, "balance": 21}]}
PERSON_RESP = {"details": [{"sex": "F", "socialService": "6 年 4 月 0 天",
                            "socialServiceDate": "2019-11-03"}]}


def _mock_oauth(env):
    responses.post(f"{BASE_URLS[env]}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "j"})


@responses.activate
def test_get_medical_period():
    _mock_oauth("prod")
    responses.get(f"{BASE_URLS['prod']}/wfm4-snowbeer/api/v1/medical/period/info/get",
                  json=MEDICAL_RESP)
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
    r = get_medical_period(CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"


@responses.activate
def test_get_employee_info_parses_social_service():
    _mock_oauth("prod")
    responses.post(f"{BASE_URLS['prod']}/hrcc/api/v1/corp1/openapi/person/search-effective",
                   json=PERSON_RESP)
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
    r = get_employee_info(CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"
