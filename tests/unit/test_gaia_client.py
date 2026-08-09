import responses
from packages.hr_domain.gaia.client import GaiaClient, BASE_URLS, from_state


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
