"""submit_leave 领域规则校验链测试（WP-02：权威时长/日期、连续-跳休、单位匹配）。"""

from types import SimpleNamespace

from apps.orchestrator.local_leave.submit import submit_leave
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.execution.context import (
    HREXecutionContext,
    bind_hr_execution_context,
)
from packages.hr_domain.identity import TrustedIdentityResolver

CTX = SimpleNamespace(state={})


class FakeGaia:
    """受控 gaia provider 假实现（不触发网络）。"""

    def __init__(self, *, perms=None, info=None, sched=None, bal=None,
                 perms_types=None, sex="F", remain=5.0):
        self.perms = perms or _permissions(perms_types or ["年休假"])
        self.info = info or _info(sex)
        self.sched = sched or _schedule(first_start="08:00")
        self.bal = bal or _balance(remain)

    def leave_permissions(self, employee_id):
        return self.perms

    def employee_info(self, employee_id):
        return self.info

    def schedule(self, start_date, end_date, employee_id):
        return self.sched

    def leave_balance(self, leave_type, employee_id):
        return self.bal

    @property
    def config(self):
        return GaiaServerConfig(corp_id="corp1", client_secret="sec",
                                grant_type="client_credentials",
                                schedule_tenant="snowbeertest")


def _permissions(types):
    return {"success": True, "data": [{"leave_code": "X", "leave_type": t} for t in types]}


def _info(sex="F"):
    return {"success": True, "data": {
        "sex": sex, "social_service_year": "6", "social_service_month": "0",
        "social_service_day": "0", "hire_month": "11", "hire_day": "03"}}


def _schedule(first_start="08:00", first_code="SCQY01", first_date="2026-07-28", rows=None):
    if rows is not None:
        return {"success": True, "data": rows}
    return {"success": True, "data": [
        {"shift_date": first_date, "shift_code": first_code, "shift_name": "班",
         "start_time": first_start, "end_time": "17:00",
         "meal_begin_time": "12:00", "meal_end_time": "13:00",
         "middle_time": None},
    ]}


def _balance(remain=5.0, name="年休假"):
    return {"success": True, "data": [{"leave_name": name, "remain": remain,
                                       "total": 5, "used": 0, "effective_year": "2026"}]}


def _resolver():
    return TrustedIdentityResolver({"user-alpha": "EMP-001"}, ref_secret="unit-secret")


def _bind(provider):
    ctx = HREXecutionContext(
        internal_user_id="user-alpha",
        identity_resolver=_resolver(),
        gaia_config=provider.config,
        gaia_provider=provider,
        request_id="req-a",
        context_id="ctx-a",
    )
    return bind_hr_execution_context(ctx)


def _common_args(**kw):
    base = dict(type_name="年休假", start_date="2026-07-28", end_date="2026-07-28",
                start_time="08:00", end_time="17:00", leave_days=1.0, reasons="家事")
    base.update(kw)
    return base


def test_no_permission():
    provider = FakeGaia(perms_types=["事假"])
    with _bind(provider):
        r = submit_leave(**_common_args(), tool_context=CTX)
    assert not r["success"] and r["error_type"] == "no_permission"


def test_gender_mismatch():
    provider = FakeGaia(perms_types=["陪产假"], sex="F")
    with _bind(provider):
        r = submit_leave(**_common_args(type_name="陪产假"), tool_context=CTX)
    assert not r["success"] and r["error_type"] == "gender_mismatch"


def test_rest_day_single_skip_rest():
    # 单日跳休落在明确休息日 → rest_day，不改期。
    rows = [{"shift_date": "2026-07-28", "shift_code": "OFF01", "shift_name": "休息",
             "start_time": "00:00", "end_time": "00:00",
             "meal_begin_time": None, "meal_end_time": None}]
    provider = FakeGaia(sched={"success": True, "data": rows})
    with _bind(provider):
        r = submit_leave(**_common_args(), tool_context=CTX)
    assert not r["success"] and r["error_type"] == "rest_day"


def test_continuous_leave_allows_rest_start():
    # 连续假（产假）首日休息日 → 不拒绝。
    rows = [{"shift_date": "2026-07-28", "shift_code": "OFF01", "shift_name": "休息",
             "start_time": "00:00", "end_time": "00:00",
             "meal_begin_time": None, "meal_end_time": None}]
    provider = FakeGaia(perms_types=["产假"], sched={"success": True, "data": rows})
    with _bind(provider):
        r = submit_leave(**_common_args(type_name="产假"), tool_context=CTX)
    assert r["success"] and r["data"]["dry_run"] is True
    assert r["data"]["form"]["typeName"] == "产假"


def test_unknown_schedule_not_treated_as_workday():
    # 排班返回空 → 跳休缺排班证据，返回 not_scheduled（不再把未知当工作日）。
    provider = FakeGaia(sched={"success": True, "data": []})
    with _bind(provider):
        r = submit_leave(**_common_args(), tool_context=CTX)
    assert not r["success"] and r["error_type"] == "not_scheduled"


def test_insufficient_balance_uses_authoritative_duration():
    provider = FakeGaia(remain=0.5)
    with _bind(provider):
        r = submit_leave(**_common_args(leave_days=1.0), tool_context=CTX)
    assert not r["success"] and r["error_type"] == "insufficient_balance"


def test_dry_run_success_authoritative_form():
    provider = FakeGaia(remain=5.0)
    with _bind(provider):
        r = submit_leave(**_common_args(), tool_context=CTX)
    assert r["success"]
    assert r["data"]["dry_run"] is True
    assert r["data"]["submitted"] is False
    payload = r["data"]["form"]
    assert payload["typeCode"] == "A31"
    assert payload["typeName"] == "年休假"
    assert payload["leaveDays"] == 1.0


def test_cross_day_end_date_plus_one():
    # 19:00 → 07:00 跨天夜班：仅取得权威时段后 end_date +1。
    rows = [{"shift_date": "2026-07-28", "shift_code": "SCQY01", "shift_name": "夜班",
             "start_time": "19:00", "end_time": "07:00",
             "meal_begin_time": None, "meal_end_time": None}]
    provider = FakeGaia(sched={"success": True, "data": rows})
    with _bind(provider):
        r = submit_leave(**_common_args(start_time="19:00", end_time="07:00",
                                        end_date="2026-07-28"), tool_context=CTX)
    assert r["success"]
    assert r["data"]["form"]["endDate"] == "2026-07-29"


def test_dry_run_disabled_calls_real_submit(monkeypatch):
    monkeypatch.setenv("GAIA_DRY_RUN", "false")
    from apps.orchestrator.local_leave.submit import _do_submit
    captured = {}

    def fake_do(payload, client, state):
        captured.update(payload=payload, state=state)
        return {"success": True, "data": {"submitted": True, "dry_run": False}}

    monkeypatch.setattr("apps.orchestrator.local_leave.submit._do_submit", fake_do)
    provider = FakeGaia(remain=5.0)
    with _bind(provider):
        r = submit_leave(**_common_args(), tool_context=CTX)
    assert r["success"] and r["data"]["submitted"] is True
    assert captured["payload"]["typeCode"] == "A31"
    assert captured["state"]["employeeId"] == "EMP-001"


def test_normalize_type_alias():
    # 年假 → 年休假；提交的 typeName/typeCode 使用标准化正式名。
    provider = FakeGaia(remain=5.0)
    with _bind(provider):
        r = submit_leave(**_common_args(type_name="年假"), tool_context=CTX)
    assert r["success"]
    assert r["data"]["form"]["typeName"] == "年休假"
    assert r["data"]["form"]["typeCode"] == "A31"
