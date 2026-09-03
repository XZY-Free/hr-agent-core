"""Orchestrator远程请求白名单、业务响应校验和失败文案。"""

from dataclasses import dataclass

import pytest

from apps.orchestrator.a2a.router import OrchestratorRemoteRouter
from packages.agent_runtime.a2a.client import (
    A2AInvocationError,
    A2AInvocationResult,
)


@dataclass
class FakeClient:
    results: list

    def __post_init__(self):
        self.calls = []

    async def invoke(self, *, base_url, request, spec):
        self.calls.append({"base_url": base_url, "request": request, "spec": spec})
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _payload(text, *, user_id="user-a", session_id="session-a"):
    return {
        "app_name": "root_agent",
        "user_id": user_id,
        "session_id": session_id,
        "new_message": {"role": "user", "parts": [{"text": text}]},
        "streaming": True,
        "state_delta": {
            "employeeId": "MUST-NOT-PROPAGATE",
            "client_secret": "MUST-NOT-PROPAGATE",
        },
    }


def _consult_result(**patch):
    data = {
        "request_id": "set-by-test",
        "status": "succeeded",
        "answer": "迟到按制度分段扣款。",
        "question_category": "hr_policy",
        "knowledge_scope": "policy",
        "sources": [{"source": "制度.docx", "score": 0.4}],
        "truncated": False,
        "recommend_hr": False,
        "agent_name": "hr-consult-agent",
        "agent_version": "1.0.0",
        "error_code": None,
    }
    data.update(patch)
    return data


def _employee_result(**patch):
    data = {
        "request_id": "set-by-test",
        "status": "succeeded",
        "answer": "您的年休假余额为4天。",
        "query_type": "leave_balance",
        "data": {"leave_balance": {"remain": 4}},
        "data_as_of": "2026-08-09T12:00:00+00:00",
        "source": "stub",
        "employee_ref": "empref_opaque",
        "partial": False,
        "agent_name": "hr-employee-data-agent",
        "agent_version": "1.0.0",
        "error_code": None,
        "retryable": False,
    }
    data.update(patch)
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "target", "factory"),
    [
        ("迟到扣款制度是什么", "hr-consult-agent", _consult_result),
        ("我还有几天年假", "hr-employee-data-agent", _employee_result),
    ],
)
async def test_remote_request_has_exact_allowlist(text, target, factory):
    client = FakeClient([])

    async def invoke(**kwargs):
        request = kwargs["request"]
        data = factory(request_id=request.request_id)
        client.calls.append(kwargs)
        return A2AInvocationResult(data=data, task_state="completed", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)

    response = await router.route(_payload(text))

    assert response.target == target
    request = client.calls[0]["request"]
    assert set(request.model_dump()) == {
        "request_id", "user_id", "session_id", "caller_agent", "locale",
        "message", "context_summary",
    }
    serialized = str(request.model_dump())
    assert "employeeId" not in serialized
    assert "client_secret" not in serialized
    assert "MUST-NOT-PROPAGATE" not in serialized


@pytest.mark.asyncio
async def test_local_routes_never_call_a2a():
    client = FakeClient([])
    router = OrchestratorRemoteRouter(client=client)
    for text in ("明天请一天年假", "打开打卡明细", "取消昨天的请假", "转人工", "确认"):
        assert await router.route(_payload(text)) is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_consult_and_employee_data_always_use_remote_agents():
    client = FakeClient([])

    async def invoke(**kwargs):
        request = kwargs["request"]
        factory = (
            _consult_result
            if kwargs["spec"].agent_name == "hr-consult-agent"
            else _employee_result
        )
        client.calls.append(kwargs)
        return A2AInvocationResult(
            data=factory(request_id=request.request_id), task_state="completed", task_id="task-t", context_id="context-c"
        )

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    assert (await router.route(_payload("迟到扣款制度是什么"))).target == "hr-consult-agent"
    assert (await router.route(_payload("我还有几天年假"))).target == "hr-employee-data-agent"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_missing_root_session_never_reaches_remote_agent():
    client = FakeClient([])

    async def session_exists(*, user_id, session_id):
        assert user_id == "user-a"
        assert session_id == "session-a"
        return False

    router = OrchestratorRemoteRouter(client=client, session_exists=session_exists)
    assert await router.route(_payload("迟到扣款制度是什么")) is None
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "error_code", "expected"),
    [
        ("迟到扣款制度是什么", "a2a_timeout", "咨询服务暂时繁忙"),
        ("迟到扣款制度是什么", "a2a_auth_failed", "咨询服务暂时繁忙"),
        ("迟到扣款制度是什么", "a2a_unavailable", "咨询服务暂时繁忙"),
        ("我还有几天年假", "a2a_unavailable", "本人数据暂时无法查询"),
        ("我还有几天年假", "a2a_contract_error", "本人数据暂时无法查询"),
        ("我还有几天年假", "a2a_security_error", "本人数据暂时无法查询"),
    ],
)
async def test_remote_failure_has_safe_target_specific_message_and_no_local_fallback(
    text, error_code, expected
):
    client = FakeClient([A2AInvocationError(error_code)])
    router = OrchestratorRemoteRouter(client=client)
    response = await router.route(_payload(text))
    assert expected in response.answer
    assert response.error_code == error_code
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "consult_url", "employee_url", "expected"),
    [
        ("迟到扣款制度是什么", "http://127.0.0.1:8199", "http://127.0.0.1:8102", "咨询服务暂时繁忙"),
        ("我还有几天年假", "http://127.0.0.1:8101", "http://127.0.0.1:8198", "本人数据暂时无法查询"),
    ],
    ids=["consult-service-stopped", "employee-service-stopped"],
)
async def test_stopped_remote_service_never_triggers_local_fallback(
    text, consult_url, employee_url, expected
):
    router = OrchestratorRemoteRouter(
        consult_url=consult_url,
        employee_data_url=employee_url,
    )
    response = await router.route(_payload(text))
    assert expected in response.answer
    assert response.error_code == "a2a_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"agent_name": "wrong-agent"},
        {"agent_version": None},
        {"request_id": "wrong-request"},
        {"client_secret": "MUST-NOT-LEAK"},
        {"answer": "您的年休假余额为99天。"},
    ],
)
async def test_invalid_or_sensitive_employee_artifact_is_never_used(patch):
    client = FakeClient([])

    async def invoke(**kwargs):
        data = _employee_result(request_id=kwargs["request"].request_id)
        data.update(patch)
        return A2AInvocationResult(data=data, task_state="completed", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    response = await router.route(_payload("我还有几天年假"))
    assert response.error_code in {"a2a_contract_error", "a2a_security_error"}
    assert "99" not in response.answer
    assert "MUST-NOT-LEAK" not in response.answer


@pytest.mark.asyncio
async def test_unknown_response_fields_are_compatible():
    client = FakeClient([])

    async def invoke(**kwargs):
        data = _consult_result(
            request_id=kwargs["request"].request_id,
            future_field={"safe": True},
        )
        return A2AInvocationResult(data=data, task_state="completed", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    response = await router.route(_payload("迟到扣款制度是什么"))
    assert response.answer == "迟到按制度分段扣款。"
    assert response.error_code is None


@pytest.mark.asyncio
async def test_document_answer_does_not_fake_knowledge_sources():
    client = FakeClient([])

    async def invoke(**kwargs):
        data = _consult_result(
            request_id=kwargs["request"].request_id,
            answer="文档包含值班安排。",
            question_category="document_qa",
            knowledge_scope=None,
            sources=[],
        )
        return A2AInvocationResult(data=data, task_state="completed", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    response = await router.route(_payload("https://example.com/a.docx 说了什么"))
    assert response.answer == "文档包含值班安排。"
    assert response.error_code is None


@pytest.mark.asyncio
async def test_knowledge_answer_without_sources_is_rejected():
    client = FakeClient([])

    async def invoke(**kwargs):
        data = _consult_result(
            request_id=kwargs["request"].request_id,
            knowledge_scope="policy",
            sources=[],
        )
        return A2AInvocationResult(data=data, task_state="completed", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    response = await router.route(_payload("迟到扣款制度是什么"))
    assert response.error_code == "a2a_contract_error"
    assert "咨询服务暂时繁忙" in response.answer


@pytest.mark.asyncio
async def test_consult_not_found_and_identity_unverified_have_frozen_user_behavior():
    client = FakeClient([])

    async def invoke(**kwargs):
        request = kwargs["request"]
        if kwargs["spec"].agent_name == "hr-consult-agent":
            data = _consult_result(
                request_id=request.request_id,
                status="not_found",
                error_code="knowledge_not_found",
            )
        else:
            data = _employee_result(
                request_id=request.request_id,
                status="rejected",
                error_code="identity_unverified",
                data=None,
                employee_ref=None,
            )
        return A2AInvocationResult(data=data, task_state="completed", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    consult = await router.route(_payload("火星基地宠物报销制度"))
    employee = await router.route(_payload("我还有几天年假"))
    assert "暂未查询到可靠制度" in consult.answer
    assert "当前身份无法完成" in employee.answer


@pytest.mark.asyncio
async def test_explicit_cross_employee_query_is_sent_only_for_service_side_rejection():
    client = FakeClient([])

    async def invoke(**kwargs):
        data = _employee_result(
            request_id=kwargs["request"].request_id,
            status="rejected",
            answer="只能查询当前员工本人的数据，不能查询其他员工。",
            query_type="rejected",
            data=None,
            source=None,
            employee_ref=None,
            error_code="cross_employee_query_not_allowed",
        )
        return A2AInvocationResult(data=data, task_state="rejected", task_id="task-t", context_id="context-c")

    client.invoke = invoke
    router = OrchestratorRemoteRouter(client=client)
    response = await router.route(_payload("他还有几天年假"))
    assert response.target == "hr-employee-data-agent"
    assert response.status == "rejected"
    assert response.error_code == "cross_employee_query_not_allowed"
    assert "不能查询其他员工" in response.answer
