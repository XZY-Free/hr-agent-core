"""Employee Data运行时职责、身份、状态和确定性数字测试。"""

from datetime import datetime, timezone

import pytest

from apps.employee_data_agent.a2a.contract import EmployeeDataA2ARequest
from apps.employee_data_agent.identity import TrustedIdentityResolver
from apps.employee_data_agent.runtime import (
    EmployeeDataObservation,
    EmployeeDataRuntime,
    EmployeeDataTurn,
)


class RecordingTurnRunner:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def run(self, request, identity, query_type):
        self.calls.append((request, identity, query_type))
        return self.turns.pop(0)


def _request(message: str, *, user_id="user-alpha", request_id="request-a"):
    return EmployeeDataA2ARequest(
        request_id=request_id,
        user_id=user_id,
        session_id="session-a",
        caller_agent="hr_orchestrator",
        locale="zh-CN",
        message=message,
        context_summary="",
    )


def _resolver():
    return TrustedIdentityResolver(
        {"user-alpha": "EMP-001", "user-beta": "EMP-002"},
        ref_secret="runtime-test-ref-secret",
    )


@pytest.mark.asyncio
async def test_balance_uses_deterministic_tool_data_and_request_clock():
    runner = RecordingTurnRunner([EmployeeDataTurn(
        tool_name="get_leave_balances",
        data={
            "leave_balances": [{"leave_code": "A31", "leave_name": "年休假",
                                "unit": "day", "effective_year": "2026",
                                "total": 5, "used": 1, "remain": 4}],
        },
        source="stub",
    )])
    times = iter([
        datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 9, 12, 1, tzinfo=timezone.utc),
    ])
    runtime = EmployeeDataRuntime(
        identity_resolver=_resolver(),
        turn_runner=runner,
        clock=lambda: next(times),
    )

    first = await runtime.run(_request("我还有几天年假", request_id="request-a"))
    runner.turns.append(EmployeeDataTurn(
        tool_name="get_leave_balances",
        data={
            "leave_balances": [{"leave_code": "A31", "leave_name": "年休假",
                                "unit": "day", "effective_year": "2026",
                                "total": 5, "used": 1, "remain": 4}],
        },
        source="stub",
    ))
    second = await runtime.run(_request("我还有几天年假", request_id="request-b"))

    assert first.status == "succeeded"
    assert first.answer == "您的年休假余额为4 天。"
    assert first.data_as_of == "2026-08-09T12:00:00+00:00"
    assert second.data_as_of == "2026-08-09T12:01:00+00:00"
    assert first.source == "stub"
    assert first.employee_ref and "EMP-001" not in first.employee_ref
    assert runner.calls[0][2] == "leave_balance_by_type"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "error_code"),
    [
        ("迟到扣款制度是什么", "policy_query_not_allowed"),
        ("明天请一天年假", "leave_request_not_allowed"),
        ("帮我查员工EMP-002的年假", "cross_employee_query_not_allowed"),
    ],
)
async def test_forbidden_requests_never_reach_model(message, error_code):
    runner = RecordingTurnRunner([])
    runtime = EmployeeDataRuntime(identity_resolver=_resolver(), turn_runner=runner)
    result = await runtime.run(_request(message))
    assert result.status == "rejected"
    assert result.error_code == error_code
    assert runner.calls == []


@pytest.mark.asyncio
async def test_unmapped_identity_is_rejected_without_employee_ref():
    runner = RecordingTurnRunner([])
    runtime = EmployeeDataRuntime(identity_resolver=_resolver(), turn_runner=runner)
    result = await runtime.run(_request("我还有几天年假", user_id="unknown-user"))
    assert result.status == "rejected"
    assert result.error_code == "identity_unverified"
    assert result.employee_ref is None
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("turn", "status", "error_code", "retryable"),
    [
        (EmployeeDataTurn(tool_name="calc_annual_leave", error_code="employee_not_found"),
         "not_found", "employee_not_found", False),
        (EmployeeDataTurn(tool_name="calc_annual_leave", error_code="gaia_auth_failed"),
         "temporarily_unavailable", "gaia_auth_failed", True),
        (EmployeeDataTurn(tool_name="calc_annual_leave", error_code="gaia_unavailable"),
         "temporarily_unavailable", "gaia_unavailable", True),
        (EmployeeDataTurn(tool_name="calc_annual_leave", error_code="internal_data_error"),
         "failed", "internal_data_error", False),
    ],
)
async def test_error_mapping(turn, status, error_code, retryable):
    runtime = EmployeeDataRuntime(
        identity_resolver=_resolver(),
        turn_runner=RecordingTurnRunner([turn]),
    )
    result = await runtime.run(_request("我还有几天年假"))
    assert result.status == status
    assert result.error_code == error_code
    assert result.retryable is retryable


@pytest.mark.asyncio
async def test_partial_data_is_success_with_explicit_marker():
    turn = EmployeeDataTurn(
        tool_name="calc_annual_leave",
        data={"annual_leave": {"mode": "flat", "quota": 5, "balance": None},
              "employment": {"social_service_year": "6"}},
        source="stub",
        partial=True,
    )
    runtime = EmployeeDataRuntime(
        identity_resolver=_resolver(),
        turn_runner=RecordingTurnRunner([turn]),
    )
    result = await runtime.run(_request("我的年假怎么折算"))
    assert result.status == "succeeded"
    assert result.partial is True
    assert result.error_code == "partial_data"


@pytest.mark.asyncio
async def test_observation_contains_tool_and_status_but_no_raw_identity_or_query(caplog):
    observations: list[EmployeeDataObservation] = []
    turn = EmployeeDataTurn(
        tool_name="get_medical_period",
        data={"medical_period": {"quota": 24, "used": 3, "balance": 21}},
        source="stub",
    )
    runtime = EmployeeDataRuntime(
        identity_resolver=_resolver(),
        turn_runner=RecordingTurnRunner([turn]),
        observer=observations.append,
    )

    with caplog.at_level("INFO", logger="apps.employee_data_agent.runtime"):
        result = await runtime.run(_request("我的医疗期余额"))

    assert result.status == "succeeded"
    assert observations[0].tool_name == "get_medical_period"
    assert observations[0].source == "stub"
    assert "EMP-001" not in caplog.text
    assert "我的医疗期余额" not in caplog.text
    assert result.employee_ref not in caplog.text
