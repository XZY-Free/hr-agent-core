"""通用A2A客户端对Task/Artifact外壳的拒绝规则。"""

from uuid import uuid4

import pytest
from a2a.types import Artifact, DataPart, Part, Task, TaskState, TaskStatus, TextPart

from packages.agent_runtime.a2a.client import (
    A2AInvocationError,
    RemoteAgentSpec,
    validate_task_result,
)
from packages.agent_runtime.a2a.context import A2ARequestContext


SPEC = RemoteAgentSpec(
    agent_name="hr-test-agent",
    agent_version="1.0.0",
    allowed_statuses=frozenset({"succeeded"}),
    required_fields=frozenset({
        "request_id", "status", "answer", "agent_name", "agent_version",
    }),
)


def _request() -> A2ARequestContext:
    return A2ARequestContext(
        request_id=str(uuid4()),
        user_id="user-a",
        session_id="session-a",
        caller_agent="hr_orchestrator",
        locale="zh-CN",
        message="测试",
        context_summary="",
    )


def _task(request: A2ARequestContext, *, data=None, parts=None, state=TaskState.completed):
    if parts is None:
        data = data or {
            "request_id": request.request_id,
            "status": "succeeded",
            "answer": "成功",
            "agent_name": "hr-test-agent",
            "agent_version": "1.0.0",
        }
        parts = [Part(root=TextPart(text="成功")), Part(root=DataPart(data=data))]
    return Task(
        id=str(uuid4()),
        context_id=request.session_id,
        status=TaskStatus(state=state),
        artifacts=[Artifact(artifact_id=str(uuid4()), parts=parts)],
    )


def test_valid_task_returns_structured_result():
    request = _request()
    result = validate_task_result(_task(request), request=request, spec=SPEC)
    assert result.data["request_id"] == request.request_id
    assert result.task_state == "completed"


@pytest.mark.parametrize(
    "task_factory",
    [
        lambda request: Task(
            id=str(uuid4()), context_id=request.session_id,
            status=TaskStatus(state=TaskState.completed), artifacts=None,
        ),
        lambda request: _task(request, parts=[Part(root=TextPart(text="无DataPart"))]),
        lambda request: _task(request, data={"request_id": request.request_id}),
        lambda request: _task(request, data={
            "request_id": "wrong-request",
            "status": "succeeded",
            "answer": "成功",
            "agent_name": "hr-test-agent",
            "agent_version": "1.0.0",
        }),
        lambda request: _task(request, data={
            "request_id": request.request_id,
            "status": "succeeded",
            "answer": "成功",
            "agent_name": "hr-test-agent",
            "agent_version": "1.0.0",
            "client_secret": "forbidden",
        }),
        lambda request: _task(request, state=TaskState.failed),
    ],
    ids=[
        "empty-artifact", "missing-datapart", "missing-fields",
        "request-id-mismatch", "sensitive-field", "task-state-mismatch",
    ],
)
def test_invalid_task_is_rejected_without_using_artifact(task_factory):
    request = _request()
    with pytest.raises(A2AInvocationError):
        validate_task_result(task_factory(request), request=request, spec=SPEC)
