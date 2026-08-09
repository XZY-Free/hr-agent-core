"""通过127.0.0.1:8101真实网络验证官方A2A协议适配。"""

import socket
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import DataPart, Message, Part, Role, Task, TextPart

from apps.consult_agent.a2a.contract import ConsultA2AResult
from apps.consult_agent.a2a.server import build_a2a_app


BASE_URL = "http://127.0.0.1:8101"


class RecordingRuntime:
    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return ConsultA2AResult(
            request_id=request.request_id,
            status="succeeded",
            answer=f"session={request.session_id}",
            question_category="hr_policy",
            knowledge_scope="policy",
            sources=[{"source": "制度.docx", "score": 0.0}],
        )


@pytest.fixture(scope="module")
def protocol_server():
    runtime = RecordingRuntime()
    server = uvicorn.Server(uvicorn.Config(
        build_a2a_app(runtime),
        host="127.0.0.1",
        port=8101,
        log_level="warning",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", 8101)) == 0:
                break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("本地A2A测试服务未启动")
    yield runtime
    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive()


def _message(
    text: str,
    *,
    request_id: str | None = None,
    user_id: str = "protocol-user",
    session_id: str = "protocol-session",
    metadata_patch: dict | None = None,
) -> Message:
    metadata = {
        "request_id": request_id or str(uuid4()),
        "user_id": user_id,
        "session_id": session_id,
        "caller_agent": "hr_orchestrator",
        "locale": "zh-CN",
        "context_summary": "协议验证使用的非敏感摘要",
    }
    if metadata_patch:
        metadata.update(metadata_patch)
    return Message(
        role=Role.user,
        message_id=str(uuid4()),
        context_id=session_id,
        metadata=metadata,
        parts=[Part(root=TextPart(text=text))],
    )


async def _official_call(message: Message, *, streaming: bool):
    async with httpx.AsyncClient(timeout=10) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
        client = ClientFactory(ClientConfig(
            streaming=streaming,
            httpx_client=http,
            supported_transports=["JSONRPC"],
        )).create(card)
        events = []
        async for event in client.send_message(message):
            events.append(event)
        return card, events


def _final_task(events) -> Task:
    tasks = [event[0] for event in events if isinstance(event, tuple)]
    assert tasks
    return tasks[-1]


def _data(task: Task) -> dict:
    assert task.artifacts
    for part in task.artifacts[-1].parts:
        if isinstance(part.root, DataPart):
            return part.root.data
    raise AssertionError("Artifact缺少DataPart")


@pytest.mark.asyncio
async def test_agent_card_is_discovered_and_parsed_by_official_resolver(protocol_server):
    async with httpx.AsyncClient() as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
    assert card.name == "hr-consult-agent"
    assert card.protocol_version == "0.3.0"
    assert card.capabilities.streaming is True
    assert len(card.skills) == 4


@pytest.mark.asyncio
async def test_standalone_health_endpoint_is_available(protocol_server):
    async with httpx.AsyncClient() as http:
        response = await http.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "agent": "hr-consult-agent",
        "version": "1.0.0",
    }


@pytest.mark.asyncio
async def test_non_streaming_returns_completed_task_and_structured_artifact(protocol_server):
    request_id = str(uuid4())
    _, events = await _official_call(
        _message("迟到扣款制度是什么", request_id=request_id),
        streaming=False,
    )
    task = _final_task(events)
    data = _data(task)
    assert task.status.state.value == "completed"
    assert data["request_id"] == request_id
    assert data["status"] == "succeeded"
    assert data["sources"] == [{"source": "制度.docx", "score": 0.0}]


@pytest.mark.asyncio
async def test_streaming_emits_sse_updates_and_finishes(protocol_server):
    _, events = await _official_call(_message("迟到扣款制度是什么"), streaming=True)
    task = _final_task(events)
    update_types = {type(event[1]).__name__ for event in events if event[1] is not None}
    assert "TaskArtifactUpdateEvent" in update_types
    assert "TaskStatusUpdateEvent" in update_types
    assert task.status.state.value == "completed"


@pytest.mark.asyncio
async def test_different_sessions_remain_isolated(protocol_server):
    _, events_a = await _official_call(
        _message("迟到扣款", user_id="same-user", session_id="session-a"),
        streaming=False,
    )
    _, events_b = await _official_call(
        _message("餐补制度", user_id="same-user", session_id="session-b"),
        streaming=False,
    )
    assert _data(_final_task(events_a))["answer"] == "session=session-a"
    assert _data(_final_task(events_b))["answer"] == "session=session-b"
    assert protocol_server.requests[-2].session_id != protocol_server.requests[-1].session_id


@pytest.mark.asyncio
async def test_sensitive_metadata_fails_before_runtime_and_never_leaks(protocol_server, caplog):
    before = len(protocol_server.requests)
    secret = "must-not-propagate-123"
    with pytest.raises(A2AClientError) as exc_info:
        await _official_call(
            _message("迟到扣款", metadata_patch={"client_secret": secret}),
            streaming=False,
        )
    assert len(protocol_server.requests) == before
    assert secret not in str(exc_info.value)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_official_client_gets_connection_error_when_service_is_absent():
    message = _message("迟到扣款")
    async with httpx.AsyncClient(timeout=0.5) as http:
        card = (await A2ACardResolver(http, BASE_URL).get_agent_card()).model_copy(
            update={"url": "http://127.0.0.1:8199/"}
        )
        client = ClientFactory(ClientConfig(
            streaming=False,
            httpx_client=http,
            supported_transports=["JSONRPC"],
        )).create(card)
        with pytest.raises(Exception) as exc_info:
            async for _ in client.send_message(message):
                pass
    assert "must-not-propagate" not in str(exc_info.value)
