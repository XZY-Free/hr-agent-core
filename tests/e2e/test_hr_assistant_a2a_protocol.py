"""通过127.0.0.1真实网络验证顶层企业人力智能助手公共A2A契约（批次6）。

录制runtime只验证协议层与公共合同；真实模型链路由评测与e2e覆盖。
本文件定位为 protocol-only：只用录制 runtime 验证协议层，不承担业务迁移验收。
业务迁移验收见 tests/e2e/production_topology/（真实 production builder + stub）。
"""

import pytest
import socket
import asyncio
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

from apps.orchestrator.public_a2a.server import build_public_a2a_app
from apps.orchestrator.public_a2a.settings import PublicA2ASettings
from apps.orchestrator.public_runtime.result import (
    completed,
    input_required,
)


pytestmark = pytest.mark.protocol

BASE_URL = ""


class RecordingRuntime:
    """按消息脚本返回公共结果的录制门面。"""

    def __init__(self):
        self.payloads = []
        self.stopped = threading.Event()

    async def cancel_pending(self, context_id, task_id):
        pass

    async def invoke(self, payload: dict):
        self.payloads.append(payload)
        message = payload["message"]
        if message == "cancel-running-protocol":
            self.stopped.clear()
            try:
                await asyncio.Event().wait()
            finally:
                self.stopped.set()
        if "请假" in message or "请年假" in message:
            return input_required(
                request_id=payload["request_id"],
                answer="请问假期类型和日期分别是什么？",
            )
        return completed(
            request_id=payload["request_id"],
            answer=f"session={payload['context_id']}",
            result_type="conversation",
            data={"echo_subject": bool(payload.get("execution_subject"))},
        )


@pytest.fixture(scope="module")
def protocol_server():
    global BASE_URL
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    BASE_URL = f"http://127.0.0.1:{port}"
    settings = PublicA2ASettings(
        listen_host="127.0.0.1", listen_port=port,
        public_base_url=BASE_URL, auth_mode="none",
    )
    runtime = RecordingRuntime()
    server = uvicorn.Server(uvicorn.Config(
        build_public_a2a_app(runtime=runtime, settings=settings),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        if server.started and thread.is_alive():
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("本地公共A2A测试服务未启动")
    yield runtime
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    assert not thread.is_alive()


def _message(
    text: str,
    *,
    context_id: str = "protocol-context",
    task_id: str | None = None,
    metadata: dict | None = None,
) -> Message:
    return Message(
        role=Role.user,
        message_id=str(uuid4()),
        context_id=context_id,
        task_id=task_id,
        metadata=metadata,
        parts=[Part(root=TextPart(text=text))],
    )


async def _official_call(message: Message, *, streaming: bool = False):
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
async def test_top_level_card_discovered_by_official_resolver(protocol_server):
    async with httpx.AsyncClient() as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
    assert card.name == "hr-assistant"
    assert card.version == "1.0.0"
    assert card.protocol_version == "0.3.0"
    assert card.preferred_transport == "JSONRPC"
    assert [skill.id for skill in card.skills] == [
        "leave-and-attendance-service",
        "employee-self-service",
        "hr-policy-and-benefits-consultation",
        "hr-system-and-document-assistance",
    ]
    serialized = card.model_dump_json(by_alias=True, exclude_none=True)
    for term in ("root_agent", "leave_agent", "hr-consult-agent",
                 "hr-employee-data-agent", "veadk", "agentkit", "gaia"):
        assert term not in serialized.lower(), term


@pytest.mark.asyncio
async def test_running_cancel_stops_work_and_both_http_stream_and_get_are_cancelled(protocol_server):
    from a2a.types import TaskIdParams, TaskQueryParams, TaskState
    async with httpx.AsyncClient(timeout=5) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
        client = ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)
        stream = client.send_message(_message("cancel-running-protocol", context_id=str(uuid4())))
        first = await anext(stream)
        task_id = first[0].id
        cancelled = await client.cancel_task(TaskIdParams(id=task_id))
        assert cancelled.status.state == TaskState.canceled
        assert protocol_server.stopped.is_set()
        events = [event async for event in stream]
        assert events[-1][0].status.state == TaskState.canceled
        persisted = await client.get_task(TaskQueryParams(id=task_id))
        assert persisted.status.state == TaskState.canceled
        assert not persisted.artifacts


@pytest.mark.asyncio
async def test_contract_discovery_endpoint_absent(protocol_server):
    """架构澄清：合同是运营方导入SnowHarness的显式请求工件，
    远程运行时不暴露合同发现端点；AgentCard发现保留为协议证据。"""
    async with httpx.AsyncClient() as http:
        card = await http.get(f"{BASE_URL}/.well-known/agent-card.json")
        contract = await http.get(
            f"{BASE_URL}/.well-known/agent-contract.json"
        )
    assert card.status_code == 200
    assert contract.status_code == 404


@pytest.mark.asyncio
async def test_health_endpoint(protocol_server):
    async with httpx.AsyncClient() as http:
        response = await http.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "agent": "hr-assistant",
        "version": "1.0.0",
        "protocol_version": "0.3.0",
        "auth_mode": "none",
    }


@pytest.mark.asyncio
async def test_non_streaming_completed_with_public_result_schema(protocol_server):
    _, events = await _official_call(_message("你好"))
    task = _final_task(events)
    data = _data(task)
    assert task.status.state.value == "completed"
    assert set(data) >= {
        "request_id", "status", "answer", "result_type", "data", "actions",
        "error_code", "retryable", "agent_name", "agent_version",
    }
    assert data["agent_name"] == "hr-assistant"
    assert data["agent_version"] == "1.0.0"
    assert data["actions"] == []
    # 内部子智能体名称不泄露。
    assert "consult" not in str(data).lower()


@pytest.mark.asyncio
async def test_streaming_transport_emits_events_without_incremental_claim(
    protocol_server,
):
    _, events = await _official_call(_message("你好"), streaming=True)
    task = _final_task(events)
    update_types = {
        type(event[1]).__name__ for event in events if event[1] is not None
    }
    assert "TaskArtifactUpdateEvent" in update_types
    assert "TaskStatusUpdateEvent" in update_types
    assert task.status.state.value == "completed"


@pytest.mark.asyncio
async def test_input_required_then_resume_same_task_and_context(protocol_server):
    context_id = f"resume-ctx-{uuid4().hex[:8]}"
    _, first_events = await _official_call(
        _message("帮我请假", context_id=context_id)
    )
    first_task = _final_task(first_events)
    assert first_task.status.state.value == "input-required"
    first_data = _data(first_task)
    assert first_data["status"] == "input_required"
    assert first_data["error_code"] == "input_required"

    # SnowHarness 补充信息：引用原taskId续发同一context。
    _, second_events = await _official_call(
        _message(
            "年休假，明天一天",
            context_id=context_id,
            task_id=first_task.id,
        )
    )
    second_task = _final_task(second_events)
    assert second_task.status.state.value == "completed"
    assert second_task.context_id == context_id
    # 恢复的是同一个任务，不是新任务。
    assert second_task.id == first_task.id
    # 门面收到的是同一request_id（=原taskId）。
    assert protocol_server.payloads[-1]["request_id"] == first_task.id
    assert protocol_server.payloads[-1]["context_id"] == context_id


@pytest.mark.asyncio
async def test_two_tasks_same_context_get_different_task_ids(protocol_server):
    context_id = f"multi-ctx-{uuid4().hex[:8]}"
    _, first_events = await _official_call(_message("你好", context_id=context_id))
    _, second_events = await _official_call(_message("再讲讲", context_id=context_id))
    first_task = _final_task(first_events)
    second_task = _final_task(second_events)
    assert first_task.context_id == second_task.context_id == context_id
    assert first_task.id != second_task.id
    assert _data(first_task)["answer"] == f"session={context_id}"
    assert _data(second_task)["answer"] == f"session={context_id}"


@pytest.mark.asyncio
async def test_sessions_are_isolated(protocol_server):
    _, events_a = await _official_call(_message("你好", context_id="iso-a"))
    _, events_b = await _official_call(_message("你好", context_id="iso-b"))
    assert _data(_final_task(events_a))["answer"] == "session=iso-a"
    assert _data(_final_task(events_b))["answer"] == "session=iso-b"


@pytest.mark.asyncio
async def test_execution_subject_flows_through_metadata(protocol_server):
    before = len(protocol_server.payloads)
    await _official_call(
        _message(
            "你好",
            metadata={
                "execution_subject": {
                    "subject_id": "snow-user-9",
                    "subject_kind": "platform_user",
                },
                "locale": "zh-CN",
            },
        )
    )
    payload = protocol_server.payloads[-1]
    assert len(protocol_server.payloads) == before + 1
    assert payload["execution_subject"] == {
        "subject_id": "snow-user-9",
        "subject_kind": "platform_user",
    }
    assert payload["context"]["locale"] == "zh-CN"


@pytest.mark.asyncio
async def test_sensitive_metadata_rejected_before_runtime(protocol_server, caplog):
    before = len(protocol_server.payloads)
    secret = "must-not-propagate-456"
    with pytest.raises(A2AClientError):
        await _official_call(
            _message("你好", metadata={"client_secret": secret})
        )
    assert len(protocol_server.payloads) == before
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_unknown_metadata_rejected_as_contract_error(protocol_server):
    before = len(protocol_server.payloads)
    with pytest.raises(A2AClientError):
        await _official_call(
            _message("你好", metadata={"caller_agent": "hr_orchestrator"})
        )
    assert len(protocol_server.payloads) == before


@pytest.mark.asyncio
async def test_completed_task_cannot_be_cancelled(protocol_server):
    """已经完成的任务不可取消。"""
    _, events = await _official_call(_message("你好"))
    task = _final_task(events)
    async with httpx.AsyncClient() as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
        client = ClientFactory(ClientConfig(
            httpx_client=http, supported_transports=["JSONRPC"]
        )).create(card)
        with pytest.raises(A2AClientError):
            from a2a.types import TaskIdParams

            await client.cancel_task(TaskIdParams(id=task.id))


@pytest.mark.asyncio
async def test_waiting_task_cancel_is_persisted_and_cannot_resume(protocol_server):
    from a2a.types import TaskIdParams, TaskQueryParams
    _, events = await _official_call(_message("我想请假", context_id=str(uuid4())))
    task = _final_task(events)
    async with httpx.AsyncClient() as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
        client = ClientFactory(ClientConfig(
            httpx_client=http, supported_transports=["JSONRPC"],
        )).create(card)
        canceled = await client.cancel_task(TaskIdParams(id=task.id))
        assert canceled.status.state.value == "canceled"
        assert (await client.get_task(TaskQueryParams(id=task.id))).status.state.value == "canceled"
    with pytest.raises(A2AClientError):
        await _official_call(_message("明天", context_id=task.context_id, task_id=task.id))


@pytest.mark.asyncio
async def test_registration_conformance_inputs_produce_expected_states(
    protocol_server,
):
    """静态注册示例的固定输入必须有真实Provider协议证明：
    basic → completed；input_required → input-required；
    resume（start→input-required，resume→completed）。"""
    # basic
    _, basic_events = await _official_call(
        _message("公司年休假的基本规则是什么？")
    )
    assert _final_task(basic_events).status.state.value == "completed"
    # input_required
    _, ir_events = await _official_call(_message("我想请假"))
    assert _final_task(ir_events).status.state.value == "input-required"
    # resume: start
    context_id = f"conf-ctx-{uuid4().hex[:8]}"
    _, start_events = await _official_call(
        _message("我想请年假", context_id=context_id)
    )
    start_task = _final_task(start_events)
    assert start_task.status.state.value == "input-required"
    # resume: 补充信息，same task/context
    _, resume_events = await _official_call(
        _message("明天一天", context_id=context_id, task_id=start_task.id)
    )
    resume_task = _final_task(resume_events)
    assert resume_task.status.state.value == "completed"
    assert resume_task.id == start_task.id
