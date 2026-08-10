"""Orchestrator固定优先级与远程上下文续接测试。"""

import pytest

from apps.orchestrator.a2a.routing import (
    DeterministicRouteTable,
    RouteTarget,
    transport_mode,
)


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("明天请一天年假", RouteTarget.LOCAL),
        ("我要请年假和事假", RouteTarget.LOCAL),
        ("改成后天", RouteTarget.LOCAL),
        ("确认", RouteTarget.LOCAL),
        ("取消昨天的请假", RouteTarget.LOCAL),
        ("我还有几天年假", RouteTarget.EMPLOYEE_DATA),
        ("我的医疗期余额", RouteTarget.EMPLOYEE_DATA),
        ("我的年假怎么折算", RouteTarget.EMPLOYEE_DATA),
        ("他还有几天年假", RouteTarget.EMPLOYEE_DATA),
        ("打开打卡明细", RouteTarget.LOCAL),
        ("迟到扣款制度是什么", RouteTarget.CONSULT),
        ("四川育儿假有几天", RouteTarget.CONSULT),
        ("https://example.com/hr.docx 这份文件说了什么", RouteTarget.CONSULT),
        ("转人工", RouteTarget.LOCAL),
        ("你好", RouteTarget.LOCAL),
    ],
)
def test_frozen_route_priority(text, target):
    assert DeterministicRouteTable().decide(
        text, user_id="user-a", session_id="session-a"
    ) == target


def test_consult_need_more_information_keeps_only_same_session_pending():
    table = DeterministicRouteTable()
    table.record_remote_status(
        user_id="user-a",
        session_id="session-a",
        target=RouteTarget.CONSULT,
        status="need_more_information",
    )
    assert table.decide("四川", user_id="user-a", session_id="session-a") == RouteTarget.CONSULT
    assert table.decide("四川", user_id="user-a", session_id="session-b") != RouteTarget.CONSULT
    table.record_remote_status(
        user_id="user-a",
        session_id="session-a",
        target=RouteTarget.CONSULT,
        status="succeeded",
    )
    assert table.decide("四川", user_id="user-a", session_id="session-a") != RouteTarget.CONSULT


def test_only_local_and_a2a_transport_values_are_accepted(monkeypatch):
    assert transport_mode("HR_CONSULT_TRANSPORT", "local") == "local"
    assert transport_mode("HR_EMPLOYEE_DATA_TRANSPORT", "a2a") == "a2a"
    with pytest.raises(RuntimeError, match="HR_CONSULT_TRANSPORT"):
        transport_mode("HR_CONSULT_TRANSPORT", "remote")
