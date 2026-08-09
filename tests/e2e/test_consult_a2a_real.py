"""真实模型、Viking与官方A2A客户端的批次3固定本地用例。"""

import json
import os
import socket
import threading
import time
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import DataPart, Message, Part, Role, Task, TextPart

from apps.consult_agent.a2a.server import build_a2a_app
from apps.consult_agent.knowledge.backend import KnowledgeBackendError
from apps.consult_agent.runtime import ConsultObservation, build_consult_runtime


BASE_URL = "http://127.0.0.1:8101"
FIXTURE_DIR = Path(__file__).parents[1] / "unit" / "fixtures"
LOG_DIR = Path(__file__).with_name("logs")
DUMMY_KEY = "dummy-for-struct-test-only"


def _has_real_config() -> bool:
    key = os.getenv("MODEL_AGENT_API_KEY")
    required = (
        "VOLCENGINE_ACCESS_KEY",
        "VOLCENGINE_SECRET_KEY",
        "KB_COLLECTION_POLICY",
        "KB_COLLECTION_HANDBOOK",
        "KB_COLLECTION_SALARY",
        "KB_COLLECTION_CHILDCARE",
    )
    return (
        bool(key)
        and key != DUMMY_KEY
        and os.getenv("KB_BACKEND") == "agentkit"
        and all(os.getenv(name, "").strip() for name in required)
    )


pytestmark = [
    pytest.mark.integration,
    pytest.mark.a2a,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_A2A_TESTS") != "true" or not _has_real_config(),
        reason="需RUN_REAL_A2A_TESTS=true及真实模型/Viking配置",
    ),
]


def _wait_for_port(port: int) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"本地测试端口未就绪：{port}")


@pytest.fixture(scope="module")
def observations():
    return []


@pytest.fixture(scope="module")
def real_a2a_server(observations):
    runtime = build_consult_runtime(observer=observations.append)
    server = uvicorn.Server(uvicorn.Config(
        build_a2a_app(runtime),
        host="127.0.0.1",
        port=8101,
        log_level="warning",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_for_port(8101)
        yield runtime
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive()


@pytest.fixture(scope="module")
def document_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 8102), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_for_port(8102)
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        assert not thread.is_alive()


@pytest.fixture(scope="module")
def evidence_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"consult-a2a-real-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    yield path
    print(f"\n[a2a-real] 脱敏证据：{path}")


def _record(
    path: Path,
    case_id: str,
    result: dict,
    tool_names: tuple[str, ...] = (),
) -> None:
    safe = {
        "case": case_id,
        "request_id": result.get("request_id"),
        "status": result.get("status"),
        "scope": result.get("knowledge_scope"),
        "source_count": len(result.get("sources", [])),
        "sources": result.get("sources", []),
        "tools": list(tool_names),
        "error_code": result.get("error_code"),
        "agent_name": result.get("agent_name"),
        "agent_version": result.get("agent_version"),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


def _message(
    text: str,
    *,
    request_id: str | None = None,
    user_id: str = "a2a-real-user",
    session_id: str | None = None,
    metadata_patch: dict | None = None,
) -> Message:
    session_id = session_id or f"a2a-real-{uuid4()}"
    metadata = {
        "request_id": request_id or str(uuid4()),
        "user_id": user_id,
        "session_id": session_id,
        "caller_agent": "hr_orchestrator",
        "locale": "zh-CN",
        "context_summary": "",
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


async def _call(message: Message, *, streaming: bool = False):
    async with httpx.AsyncClient(timeout=180) as http:
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
    raise AssertionError("A2A Artifact缺少DataPart")


FIXED_CASES = [
    {
        "id": "policy_late_fine",
        "message": "迟到扣款制度是什么",
        "status": "succeeded",
        "scope": "policy",
        "tool": "kb_search",
        "require_sources": True,
    },
    {
        "id": "childcare_sichuan",
        "message": "四川育儿假有几天",
        "status": "succeeded",
        "scope": "childcare",
        "tool": "kb_search",
        "any_keywords": ["10天", "10 天", "十天"],
        "require_sources": True,
    },
    {
        "id": "childcare_asks_province",
        "message": "育儿假有几天",
        "status": "need_more_information",
        "forbidden_tool": "kb_search",
        "any_keywords": ["省", "地区", "哪个", "所在"],
    },
    {
        "id": "salary_term_alias",
        "message": "餐补的标准在哪看",
        "status": "succeeded",
        "scope": "salary",
        "tool": "kb_search",
        "require_sources": True,
    },
    {
        "id": "handbook_operation",
        "message": "人事系统考勤怎么操作",
        "status_any": ["succeeded", "not_found"],
        "scope": "handbook",
        "tool": "kb_search",
        "require_sources": True,
    },
    {
        "id": "personal_data_rejected",
        "message": "我还有几天年假",
        "status": "rejected",
        "error_code": "personal_data_not_allowed",
        "forbidden_tool": "kb_search",
        "forbidden_numbers": True,
    },
    {
        "id": "leave_request_rejected",
        "message": "明天请一天年假",
        "status": "rejected",
        "error_code": "leave_request_not_allowed",
        "forbidden_tool": "kb_search",
    },
    {
        "id": "non_hr_rejected",
        "message": "我电脑坏了怎么报修",
        "status": "rejected",
        "error_code": "out_of_scope",
        "forbidden_tool": "kb_search",
    },
    {
        "id": "knowledge_not_found",
        "message": "火星基地宠物报销制度",
        "status": "not_found",
        "error_code": "knowledge_not_found",
        "tool": "kb_search",
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXED_CASES, ids=[case["id"] for case in FIXED_CASES])
async def test_fixed_real_a2a_cases(case, real_a2a_server, observations, evidence_path):
    request_id = str(uuid4())
    before = len(observations)
    _, events = await _call(_message(case["message"], request_id=request_id))
    task = _final_task(events)
    result = _data(task)

    assert result["request_id"] == request_id
    if expected := case.get("status"):
        assert result["status"] == expected
    else:
        assert result["status"] in case["status_any"]
    if scope := case.get("scope"):
        assert result["knowledge_scope"] == scope
    if error_code := case.get("error_code"):
        assert result["error_code"] == error_code
    if case.get("require_sources"):
        assert result["sources"]
        assert all(row["source"] and isinstance(row["score"], (int, float))
                   for row in result["sources"])
    if keywords := case.get("any_keywords"):
        assert any(keyword in result["answer"] for keyword in keywords)
    if case.get("forbidden_numbers"):
        assert not any(char.isdigit() for char in result["answer"])
    assert len(observations) == before + 1
    if expected := case.get("tool"):
        assert expected in observations[-1].tool_names
    if forbidden := case.get("forbidden_tool"):
        assert forbidden not in observations[-1].tool_names
    assert "get_leave_balance" not in observations[-1].tool_names
    assert "get_medical_period" not in observations[-1].tool_names
    _record(evidence_path, case["id"], result, observations[-1].tool_names)


class _FailingKnowledgeBackend:
    def search(self, query, *, scope, top_k):
        raise KnowledgeBackendError("knowledge_network_error")


@pytest.mark.asyncio
async def test_knowledge_failure_is_temporarily_unavailable(
    real_a2a_server,
    monkeypatch,
    observations,
    evidence_path,
):
    import apps.consult_agent.tools.kb_search as kb_module

    monkeypatch.setattr(kb_module, "get_backend", lambda: _FailingKnowledgeBackend())
    before = len(observations)
    _, events = await _call(_message("迟到扣款制度是什么"))
    task = _final_task(events)
    result = _data(task)
    assert task.status.state.value == "failed"
    assert result["status"] == "temporarily_unavailable"
    assert result["error_code"] == "knowledge_network_error"
    assert not result["sources"]
    assert len(observations) == before + 1
    assert "kb_search" in observations[-1].tool_names
    _record(
        evidence_path,
        "knowledge_failure_injection",
        result,
        observations[-1].tool_names,
    )


@pytest.mark.asyncio
async def test_document_link_uses_parser_not_knowledge(
    real_a2a_server,
    document_server,
    observations,
    evidence_path,
):
    before = len(observations)
    _, events = await _call(_message(
        "http://127.0.0.1:8102/notice.md 这份人力通知说了什么"
    ))
    result = _data(_final_task(events))
    assert result["status"] == "succeeded"
    assert result["question_category"] == "hr_document"
    assert len(observations) == before + 1
    assert "parse_document" in observations[-1].tool_names
    assert "kb_search" not in observations[-1].tool_names
    _record(evidence_path, "document_qa", result, observations[-1].tool_names)


@pytest.mark.asyncio
async def test_missing_required_field_is_protocol_error(real_a2a_server, evidence_path):
    message = _message("迟到扣款制度是什么")
    metadata = dict(message.metadata)
    del metadata["locale"]
    message.metadata = metadata
    with pytest.raises(A2AClientError):
        await _call(message)
    _record(evidence_path, "missing_required_field", {
        "status": "protocol_error",
        "error_code": "invalid_params",
    })


@pytest.mark.asyncio
async def test_agent_card_nonstream_sse_and_same_context_followup(
    real_a2a_server,
    evidence_path,
):
    session_id = f"same-context-{uuid4()}"
    request_id = str(uuid4())
    card, first_events = await _call(_message(
        "育儿假有几天",
        request_id=request_id,
        session_id=session_id,
    ))
    first = _data(_final_task(first_events))
    assert card.name == "hr-consult-agent"
    assert card.protocol_version == "0.3.0"
    assert card.capabilities.streaming is True
    assert len(card.skills) == 4
    assert first["request_id"] == request_id
    assert first["status"] == "need_more_information"

    _, second_events = await _call(_message(
        "四川",
        session_id=session_id,
    ), streaming=True)
    second_task = _final_task(second_events)
    second = _data(second_task)
    update_types = {
        type(event[1]).__name__
        for event in second_events
        if isinstance(event, tuple) and event[1] is not None
    }
    assert "TaskArtifactUpdateEvent" in update_types
    assert "TaskStatusUpdateEvent" in update_types
    assert second_task.status.state.value == "completed"
    assert second["status"] == "succeeded"
    assert second["knowledge_scope"] == "childcare"
    assert any(keyword in second["answer"] for keyword in ("10天", "10 天", "十天"))
    _record(evidence_path, "same_context_followup", second)


@pytest.mark.asyncio
async def test_different_session_ids_do_not_mix(real_a2a_server):
    _, first_events = await _call(_message(
        "我还有几天年假",
        session_id=f"isolated-a-{uuid4()}",
    ))
    _, second_events = await _call(_message(
        "明天请一天年假",
        session_id=f"isolated-b-{uuid4()}",
    ))
    assert _data(_final_task(first_events))["error_code"] == "personal_data_not_allowed"
    assert _data(_final_task(second_events))["error_code"] == "leave_request_not_allowed"
