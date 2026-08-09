import responses
from types import SimpleNamespace
from packages.hr_domain.gaia.client import BASE_URLS
from packages.hr_domain.gaia.schedule_query import get_schedule

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


@responses.activate
def test_get_schedule():
    _mock_oauth("sandbox")
    responses.post(f"{BASE_URLS['sandbox']}/wfm4customization/api/v1/scheduling/attendance/getScheduleData",
                   json=SCHEDULE_RESP)
    r = get_schedule("2026-07-27", "2026-07-28", CTX)
    assert r["success"] and len(r["data"]) == 2
    assert r["data"][1]["shift_code"] == "SCQY057"
    assert r["data"][0]["shift_name"] == "休息"
    # tenant 固定 snowbeertest；请求体日期透传
    req = responses.calls[1].request
    assert req.headers["tenant"] == "snowbeertest"
    body = req.body.decode() if isinstance(req.body, bytes) else req.body
    assert '"2026-07-27"' in body and '"2026-07-28"' in body
    assert '"snowbeertest"' not in body  # tenant 走 header 不进 body


@responses.activate
def test_get_schedule_gaia_error():
    responses.post(f"{BASE_URLS['sandbox']}/identity/api/v1/oauth",
                   json={"result": False, "code": 500, "message": "down"})
    r = get_schedule("2026-07-27", "2026-07-28", CTX)
    assert not r["success"] and r["error_type"] == "gaia_error"
