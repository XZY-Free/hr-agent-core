import responses
from types import SimpleNamespace

from packages.hr_domain.gaia.client import BASE_URLS
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.gaia.leave_query import get_leave_balance, get_leave_permissions
from packages.hr_domain.execution.context import (
    HREXecutionContext,
    bind_hr_execution_context,
)
from packages.hr_domain.identity import TrustedIdentityResolver

STATE = {"employeeId": "E001", "corp_id": "corp1",
         "client_secret": "sec", "grant_type": "client_credentials"}
CTX = SimpleNamespace(state=STATE)   # 单测中模拟 ToolContext（不再读取其凭据）

BALANCE_RESP = {"code": 200, "details": {"employeeData": [{"employeeDetailData": [
    {"effectiveYear": "2026", "leaveCode": "A31", "leaveName": "年休假",
     "leaveUsed": 1, "leaveTotal": 5, "leaveRemain": 4},
    {"effectiveYear": "2026", "leaveCode": "A47", "leaveName": "育儿假",
     "leaveUsed": 0, "leaveTotal": 10, "leaveRemain": 10},
]}]}}


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
def test_get_leave_balance_filters_by_type():
    _mock_oauth("prod")
    responses.post(f"{BASE_URLS['prod']}/wfm4integration-wfm4appapi/api/v1/gaiastandard/getemployeeleaveremaindata/corp1",
                   json=BALANCE_RESP)
    with _bind_context():
        r = get_leave_balance("年休假", CTX)
    assert r["success"] and len(r["data"]) == 1
    assert r["data"][0]["remain"] == 4
    assert r["data"][0]["leave_name"] == "年休假"


@responses.activate
def test_get_leave_balance_all_when_empty_filter():
    _mock_oauth("prod")
    responses.post(f"{BASE_URLS['prod']}/wfm4integration-wfm4appapi/api/v1/gaiastandard/getemployeeleaveremaindata/corp1",
                   json=BALANCE_RESP)
    with _bind_context():
        r = get_leave_balance("", CTX)
    assert r["success"] and len(r["data"]) == 2


@responses.activate
def test_get_leave_permissions():
    _mock_oauth("sandbox")
    responses.post(f"{BASE_URLS['sandbox']}/atd-webapi/api/gaiaStandard/leave/getEmployeeCanApplyLeaveType/corp1",
                   json={"result": True, "data": [{"LeaveCode": "A31", "LeaveType": "年休假"}]})
    with _bind_context():
        r = get_leave_permissions(CTX)
    assert r["success"] and r["data"] == [{"leave_code": "A31", "leave_type": "年休假"}]


@responses.activate
def test_get_leave_permissions_result_false_returns_err():
    _mock_oauth("sandbox")
    responses.post(f"{BASE_URLS['sandbox']}/atd-webapi/api/gaiaStandard/leave/getEmployeeCanApplyLeaveType/corp1",
                   json={"result": False, "message": "denied"})
    with _bind_context():
        r = get_leave_permissions(CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"
    assert "denied" not in r["message"]
    assert "管理员" in r["message"]


@responses.activate
def test_balance_gaia_down_returns_err():
    responses.post(f"{BASE_URLS['prod']}/identity/api/v1/oauth",
                   json={"result": False, "code": 500, "message": "boom"})
    with _bind_context():
        r = get_leave_balance("", CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"


def test_balance_identity_unverified_without_binding():
    # 无 HR execution context → identity_unverified，不访问 Gaia
    r = get_leave_balance("", CTX)
    assert not r["success"] and r["error_type"] == "identity_unverified"


def test_balance_identity_unverified_when_unmapped():
    with _bind_context(user_id="unknown-user"):
        r = get_leave_balance("", CTX)
    assert not r["success"] and r["error_type"] == "identity_unverified"
