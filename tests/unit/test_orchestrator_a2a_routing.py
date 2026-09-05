"""Orchestrator固定优先级与远程上下文续接测试。"""

import pytest

from apps.orchestrator.a2a.routing import (
    DeterministicRouteTable,
    RouteTarget,
)
from apps.orchestrator.a2a.router import OrchestratorRemoteRouter
from packages.agent_runtime.a2a.client import A2AInvocationResult
from packages.hr_domain.documents.context import encode_document_context


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


class _RecordingClient:
    def __init__(self):
        self.requests = []

    async def invoke(self, *, base_url, request, spec):
        self.requests.append(request)
        return A2AInvocationResult(data={
            "request_id": request.request_id,
            "status": "succeeded",
            "answer": "文档答案",
            "question_category": "hr_document",
            "knowledge_scope": None,
            "sources": [],
            "truncated": False,
            "recommend_hr": False,
            "agent_name": "hr-consult-agent",
            "agent_version": "1.0.0",
            "error_code": None,
        }, task_state="completed", task_id="task-t", context_id="context-c")


@pytest.mark.asyncio
async def test_document_context_provider_passes_only_the_allowlisted_summary():
    client = _RecordingClient()
    expected = encode_document_context({
        "documents": [{
            "canonical_reference": "ref-1",
            "url": "https://example.com/notice.docx",
            "content": "春节值班安排",
        }]
    })

    async def context_summary_provider(**kwargs):
        assert kwargs["message"].startswith("https://example.com/notice.docx")
        return expected

    router = OrchestratorRemoteRouter(
        client=client,
        session_exists=lambda **kwargs: _async_value(True),
        context_summary_provider=context_summary_provider,
    )
    response = await router.route({
        "user_id": "user-a",
        "session_id": "session-a",
        "new_message": {
            "parts": [{"text": "https://example.com/notice.docx 这份文件说了什么"}]
        },
    })

    assert response.status == "succeeded"
    assert client.requests[0].context_summary == expected
    assert "employeeId" not in client.requests[0].context_summary


async def _async_value(value):
    return value
