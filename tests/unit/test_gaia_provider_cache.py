"""共享 GaiaProvider 的 JWT 缓存复用与账号隔离不变量。

WP-01 shared Gaia Authority：一个共享的 GaiaProvider 必须在连续读取之间复用其
真实的 GaiaClient / JWT 缓存，而不是每次 `_client()` 都新建一个空缓存的 client。
同时生产 / sandbox 与不同 server config 之间，凭据与令牌必须完全隔离。

只使用真实 GaiaProvider + GaiaClient 逻辑（绝不伪造 client / 缓存结果）；全部
HTTP 经 responses 在传输层拦截，产物是 fixture 假凭据 / 假 token，绝不发起网络。
"""

import json
import threading
import urllib.parse

import responses

from packages.hr_domain.gaia.client import BASE_URLS, JWT_TTL_SECONDS
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider

PROD = BASE_URLS["prod"]
SANDBOX = BASE_URLS["sandbox"]
OAUTH = "/identity/api/v1/oauth"


def make_config(corp="corp1", secret="sec1", grant="client_credentials", tenant="tenant1"):
    return GaiaServerConfig(corp_id=corp, client_secret=secret, grant_type=grant,
                            schedule_tenant=tenant)


def make_provider(corp="corp1", secret="sec1"):
    return GaiaProvider(make_config(corp=corp, secret=secret), backend="gaia")


def oauth_calls(base_url=None):
    return [c for c in responses.calls
            if OAUTH in c.request.url and (base_url is None or base_url in c.request.url)]


EMPLOYEE_BODY = {
    "details": [{
        "sex": "F",
        "socialService": "6 年 4 月 0 天",
        "socialServiceDate": "2019-11-03",
    }],
    "result": True,
    "code": 200,
}

LEAVE_ROW = {
    "leaveCode": "A31", "leaveName": "年休假", "effectiveYear": "2026",
    "leaveUnit": "day", "leaveTotal": 5, "leaveUsed": 1, "leaveRemain": 4,
    "leaveApproving": 0, "freeze": 0,
}
LEAVE_BODY = {"details": {"employeeData": [{"employeeDetailData": [LEAVE_ROW]}]}, "code": 200}


@responses.activate
def test_prod_reads_reuse_one_prod_token():
    responses.post(f"{PROD}{OAUTH}", json={"result": True, "code": 200, "data": "prod.jwt"})
    responses.post(f"{PROD}/hrcc/api/v1/corp1/openapi/person/search-effective",
                   json=EMPLOYEE_BODY)
    responses.post(
        f"{PROD}/wfm4integration-wfm4appapi/api/v1/gaiastandard/getemployeeleaveremaindata/corp1",
        json=LEAVE_BODY,
    )

    p = make_provider()

    emp = p.employee_info("EMP-001")
    leave = p.leave_balance("年休假", "EMP-001")

    # 解析结果正确，而不仅是类型/内部对象相等。
    assert emp["success"] is True
    assert emp["data"]["sex"] == "F"
    assert emp["data"]["social_service_year"] == "6"
    assert emp["data"]["social_service_month"] == "4"
    assert emp["data"]["social_service_day"] == "0"
    assert emp["data"]["hire_month"] == "11"
    assert emp["data"]["hire_day"] == "03"

    assert leave["success"] is True
    assert leave["data"] == [{
        "leave_code": "A31", "leave_name": "年休假", "effective_year": "2026",
        "unit": "day", "total": 5, "used": 1, "remain": 4, "approving": 0, "freeze": 0,
    }]

    # 不变量：两次生产读共享同一个 prod OAuth（只发一次），读请求都带该 token。
    assert len(oauth_calls(PROD)) == 1
    read_auth = [c.request.headers["Authorization"] for c in responses.calls
                 if "search-effective" in c.request.url
                 or "getemployeeleaveremaindata" in c.request.url]
    assert read_auth == ["Bearer prod.jwt", "Bearer prod.jwt"]


@responses.activate
def test_sandbox_reads_reuse_one_sandbox_token_and_stay_isolated_from_prod():
    responses.post(f"{SANDBOX}{OAUTH}", json={"result": True, "code": 200, "data": "sbx.jwt"})
    responses.post(
        f"{SANDBOX}/atd-webapi/api/gaiaStandard/leave/getEmployeeCanApplyLeaveType/corp1",
        json={"result": True, "data": [{"LeaveCode": "A31", "LeaveType": "年休假"}]},
    )
    responses.post(f"{SANDBOX}/wfm4customization/api/v1/scheduling/attendance/getScheduleData",
                   json={"details": {"employeeData": [{"employeeDetailData": [
                       {"shiftDate": "2026-09-03", "shiftCode": "SCQY01", "shiftName": "白班",
                        "startTime": "08:00", "endTime": "17:00"},
                   ]}]}})

    p = make_provider()

    perm = p.leave_permissions("EMP-001")
    sch = p.schedule("2026-09-03", "2026-09-03", "EMP-001")

    assert perm["success"] is True
    assert perm["data"] == [{"leave_code": "A31", "leave_type": "年休假"}]
    assert sch["success"] is True
    assert sch["data"] == [{
        "shift_date": "2026-09-03", "shift_code": "SCQY01", "shift_name": "白班",
        "start_time": "08:00", "end_time": "17:00",
        "meal_begin_time": None, "meal_end_time": None, "middle_time": None,
    }]

    # 两个 sandbox 读共享同一个 sandbox token，且生产侧从未借用该 token。
    assert len(oauth_calls(SANDBOX)) == 1
    assert len(oauth_calls(PROD)) == 0


@responses.activate
def test_providers_with_different_configs_never_share_token():
    def oauth_cb(request):
        secret = urllib.parse.parse_qs(request.body).get("client_secret", [""])[0]
        return (200, {}, json.dumps({"result": True, "code": 200, "data": f"jwt-{secret}"}))

    responses.add_callback(responses.POST, f"{PROD}{OAUTH}", callback=oauth_cb)
    responses.post(f"{PROD}/hrcc/api/v1/corpA/openapi/person/search-effective", json=EMPLOYEE_BODY)
    responses.post(f"{PROD}/hrcc/api/v1/corpB/openapi/person/search-effective", json=EMPLOYEE_BODY)

    pa = make_provider(corp="corpA", secret="secretA")
    pb = make_provider(corp="corpB", secret="secretB")

    assert pa.employee_info("E1")["success"] is True
    assert pb.employee_info("E1")["success"] is True

    # 每个 provider 携带自己凭据派生出的 token，绝不跨 config 共享。
    read_auth = sorted(c.request.headers["Authorization"] for c in responses.calls
                       if "search-effective" in c.request.url)
    assert read_auth == ["Bearer jwt-secretA", "Bearer jwt-secretB"]


@responses.activate
def test_expired_token_refreshes_once_then_reused(monkeypatch):
    import packages.hr_domain.gaia.client as client_mod

    clock = {"now": 1000.0}
    monkeypatch.setattr(client_mod.time, "time", lambda: clock["now"])

    oauth_count = {"n": 0}

    def oauth_cb(request):
        oauth_count["n"] += 1
        return (200, {}, json.dumps({"result": True, "code": 200, "data": f"jwt-{oauth_count['n']}"}))

    responses.add_callback(responses.POST, f"{PROD}{OAUTH}", callback=oauth_cb)
    responses.post(f"{PROD}/hrcc/api/v1/corp1/openapi/person/search-effective", json=EMPLOYEE_BODY)
    responses.post(
        f"{PROD}/wfm4integration-wfm4appapi/api/v1/gaiastandard/getemployeeleaveremaindata/corp1",
        json=LEAVE_BODY,
    )

    p = make_provider()

    assert p.employee_info("E1")["success"] is True
    assert oauth_count["n"] == 1  # jwt-1 已缓存在共享 client

    # 过期后下一次读取应刷新一次，并让后续读取复用刷新后的 token。
    clock["now"] = 1000.0 + JWT_TTL_SECONDS + 1

    assert p.leave_balance("年休假", "E1")["success"] is True
    assert oauth_count["n"] == 2

    assert p.employee_info("E1")["success"] is True
    assert oauth_count["n"] == 2  # 刷新后的 token 被复用，不再发第三次


@responses.activate
def test_oauth_failure_is_not_cached_as_success_and_never_falls_back_to_stub():
    responses.post(f"{PROD}{OAUTH}",
                   json={"result": False, "code": 500, "message": "bad secret"})

    p = make_provider()  # 显式 backend="gaia"，绝不回退 stub

    r1 = p.employee_info("E1")
    r2 = p.leave_balance("年休假", "E1")

    assert r1["success"] is False
    assert r1["error_type"] == "gaia_error"
    assert r2["success"] is False
    assert r2["error_type"] == "gaia_error"

    # 失败绝不能当作成功缓存：下一次读取仍会重试 OAuth。
    assert len(oauth_calls(PROD)) == 2


@responses.activate
def test_concurrent_reads_do_not_refresh_per_thread(monkeypatch):
    import packages.hr_domain.gaia.client as client_mod

    clock = {"now": 1000.0}
    monkeypatch.setattr(client_mod.time, "time", lambda: clock["now"])

    oauth_count = {"n": 0}
    count_lock = threading.Lock()

    def oauth_cb(request):
        with count_lock:
            oauth_count["n"] += 1
            token = f"jwt-{oauth_count['n']}"
        return (200, {}, json.dumps({"result": True, "code": 200, "data": token}))

    responses.add_callback(responses.POST, f"{PROD}{OAUTH}", callback=oauth_cb)
    responses.post(f"{PROD}/hrcc/api/v1/corp1/openapi/person/search-effective", json=EMPLOYEE_BODY)

    p = make_provider()

    assert p.employee_info("E1")["success"] is True
    assert oauth_count["n"] == 1  # jwt-1 缓存在共享 client

    # 让所有并发读取都必须刷新同一个过期 token。
    clock["now"] = 1000.0 + JWT_TTL_SECONDS + 1

    n_threads = 4
    gate = threading.Event()  # 同时放行，不 sleep
    results = []

    def worker():
        gate.wait(timeout=10)
        results.append(p.employee_info("EMP-001"))

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(timeout=20)

    assert not any(t.is_alive() for t in threads)
    assert all(r["success"] is True for r in results)
    # 共享 provider 只刷新一次，而不是每个线程各刷新一次。
    assert oauth_count["n"] == 2


@responses.activate
def test_cold_start_concurrent_reads_share_one_client_and_one_token():
    # 冷启动并发首读：provider 构造后没有任何预热读取。构造不得触碰网络（gaia
    # 后端在构造时即建 client 但无 I/O）；并发首读必须共享同一个 gaia client / JWT，
    # 只发一次 OAuth（各线程不能各自 new 一个 client 而重复授权）。
    oauth_count = {"n": 0}
    count_lock = threading.Lock()

    def oauth_cb(request):
        with count_lock:
            oauth_count["n"] += 1
            token = f"jwt-{oauth_count['n']}"
        return (200, {}, json.dumps({"result": True, "code": 200, "data": token}))

    responses.add_callback(responses.POST, f"{PROD}{OAUTH}", callback=oauth_cb)
    responses.post(f"{PROD}/hrcc/api/v1/corp1/openapi/person/search-effective", json=EMPLOYEE_BODY)

    p = make_provider()
    assert oauth_count["n"] == 0  # 构造不触发任何 OAuth（无 I/O）

    n_threads = 4
    gate = threading.Event()
    results = []

    def worker():
        gate.wait(timeout=10)
        results.append(p.employee_info("EMP-001"))

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(timeout=20)

    assert not any(t.is_alive() for t in threads)
    assert all(r["success"] is True for r in results)
    assert oauth_count["n"] == 1  # 单次 OAuth，共享同一 client / token
