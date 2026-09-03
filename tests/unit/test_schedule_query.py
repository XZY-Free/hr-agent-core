import pytest
import responses
from types import SimpleNamespace

from packages.hr_domain.gaia.client import BASE_URLS
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.gaia.schedule_query import get_schedule
from packages.hr_domain.execution.context import (
    HREXecutionContext,
    bind_hr_execution_context,
)
from packages.hr_domain.identity import TrustedIdentityResolver

STATE = {"employeeId": "E001", "corp_id": "corp1",
         "client_secret": "sec", "grant_type": "client_credentials"}
CTX = SimpleNamespace(state=STATE)

SCHEDULE_RESP = {"details": {"employeeData": [{"employeeDetailData": [
    {"shiftDate": "2026-07-27", "shiftCode": "OFF01", "shiftName": "休息",
     "startTime": "00:00", "endTime": "00:00"},
    {"shiftDate": "2026-07-28", "shiftCode": "SCQY057", "shiftName": "西昌工厂包装（夜班）",
     "startTime": "19:00", "endTime": "07:00"},
]}]}}


def _mock_oauth(env):
    responses.post(f"{BASE_URLS[env]}/identity/api/v1/oauth",
                   json={"result": True, "code": 200, "data": "j"})


def _resolver():
    return TrustedIdentityResolver({"user-alpha": "E001"}, ref_secret="unit-secret")


def _bind_context(gaia_config=None):
    config = gaia_config or GaiaServerConfig(
        corp_id="corp1", client_secret="sec", grant_type="client_credentials",
        schedule_tenant="snowbeertest",
    )
    ctx = HREXecutionContext(
        internal_user_id="user-alpha",
        identity_resolver=_resolver(),
        gaia_config=config,
        gaia_provider=GaiaProvider(config),
        request_id="req-a",
        context_id="ctx-a",
    )
    return bind_hr_execution_context(ctx)


@responses.activate
def test_get_schedule():
    _mock_oauth("sandbox")
    responses.post(f"{BASE_URLS['sandbox']}/wfm4customization/api/v1/scheduling/attendance/getScheduleData",
                   json=SCHEDULE_RESP)
    with _bind_context():
        r = get_schedule("2026-07-27", "2026-07-28", CTX)
    assert r["success"] and len(r["data"]) == 2
    assert r["data"][1]["shift_code"] == "SCQY057"
    assert r["data"][0]["shift_name"] == "休息"
    # tenant 来自服务端 GAIA_SCHEDULE_TENANT；请求体日期透传
    req = responses.calls[1].request
    assert req.headers["tenant"] == "snowbeertest"
    body = req.body.decode() if isinstance(req.body, bytes) else req.body
    assert '"2026-07-27"' in body and '"2026-07-28"' in body
    assert '"snowbeertest"' not in body  # tenant 走 header 不进 body


@responses.activate
def test_get_schedule_gaia_error():
    responses.post(f"{BASE_URLS['sandbox']}/identity/api/v1/oauth",
                   json={"result": False, "code": 500, "message": "down"})
    with _bind_context():
        r = get_schedule("2026-07-27", "2026-07-28", CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"


def test_get_schedule_identity_unverified_without_binding():
    # 无 HR execution context → fail closed identity_unverified，不访问 Gaia
    r = get_schedule("2026-07-27", "2026-07-28", CTX)
    assert not r["success"] and r["error_type"] == "identity_unverified"


def test_get_schedule_identity_unverified_when_unmapped():
    config = GaiaServerConfig(
        corp_id="corp1", client_secret="sec", grant_type="client_credentials",
        schedule_tenant="snowbeertest",
    )
    ctx = HREXecutionContext(
        internal_user_id="unknown-user",
        identity_resolver=_resolver(),
        gaia_config=config,
        gaia_provider=GaiaProvider(config),
        request_id="req-a",
        context_id="ctx-a",
    )
    with bind_hr_execution_context(ctx):
        r = get_schedule("2026-07-27", "2026-07-28", CTX)
    assert not r["success"] and r["error_type"] == "identity_unverified"


@pytest.mark.parametrize(
    "set_env,missing",
    [
        ([("GAIA_CORP_ID", "corp1"), ("GAIA_CLIENT_SECRET", "sec"),
          ("GAIA_GRANT_TYPE", "client_credentials")], "GAIA_SCHEDULE_TENANT"),
        ([("GAIA_CORP_ID", "corp1"), ("GAIA_CLIENT_SECRET", "sec"),
          ("GAIA_SCHEDULE_TENANT", "snowbeertest")], "GAIA_GRANT_TYPE"),
        ([("GAIA_CORP_ID", "corp1"), ("GAIA_GRANT_TYPE", "client_credentials"),
          ("GAIA_SCHEDULE_TENANT", "snowbeertest")], "GAIA_CLIENT_SECRET"),
        ([("GAIA_CLIENT_SECRET", "sec"), ("GAIA_GRANT_TYPE", "client_credentials"),
          ("GAIA_SCHEDULE_TENANT", "snowbeertest")], "GAIA_CORP_ID"),
    ],
)
def test_gaia_prod_config_missing_fails_closed(monkeypatch, set_env, missing):
    # 任一生产必需配置缺失（含 GAIA_SCHEDULE_TENANT）→ fail closed
    for name in ["GAIA_CORP_ID", "GAIA_CLIENT_SECRET", "GAIA_GRANT_TYPE",
                 "GAIA_SCHEDULE_TENANT"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in set_env:
        monkeypatch.setenv(name, value)
    from packages.hr_domain.gaia.config import gaia_server_config_from_env
    with pytest.raises(RuntimeError, match="Gaia服务端配置缺失"):
        gaia_server_config_from_env()
