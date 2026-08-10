"""Employee Data真实模型、显式Stub与官方A2A客户端的8102网络门禁。"""

import json
import os
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import DataPart, Message, Part, Role, Task, TextPart

from apps.employee_data_agent.a2a.server import build_a2a_app
from apps.employee_data_agent.agent import build_employee_data_agent
from apps.employee_data_agent.identity import TrustedIdentityResolver
from apps.employee_data_agent.provider import StubEmployeeDataProvider
from apps.employee_data_agent.runtime import (
    EmployeeDataRuntime,
    VeADKEmployeeDataTurnRunner,
)
from packages.agent_runtime.model_config import extra_config_for, model_for


BASE_URL = "http://127.0.0.1:8102"
LOG_DIR = Path(__file__).with_name("logs")
DUMMY_KEY = "dummy-for-struct-test-only"


def _has_real_key() -> bool:
    key = os.getenv("MODEL_AGENT_API_KEY")
    return bool(key) and key != DUMMY_KEY


pytestmark = [
    pytest.mark.integration,
    pytest.mark.a2a,
    pytest.mark.employee_data_a2a,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_EMPLOYEE_A2A_TESTS") != "true" or not _has_real_key(),
        reason="需RUN_REAL_EMPLOYEE_A2A_TESTS=true及真实模型Key",
    ),
]


def _records():
    return {
        "EMP-001": {
            "annual_leave": {
                "mode": "flat", "quota": 5,
                "balance": [{"leave_name": "年休假", "total": 5, "used": 1, "remain": 4}],
            },
            "employment": {
                "social_service_year": "6", "social_service_month": "4",
                "social_service_day": "0", "hire_month": "11", "hire_day": "03",
            },
            "medical_period": {"quota": 24, "used": 3, "balance": 21},
        },
        "EMP-002": {
            "annual_leave": {
                "mode": "flat", "quota": 10,
                "balance": [{"leave_name": "年休假", "total": 10, "used": 2, "remain": 8}],
            },
            "employment": {
                "social_service_year": "12", "social_service_month": "1",
                "social_service_day": "0", "hire_month": "02", "hire_day": "15",
            },
            "medical_period": {"quota": 18, "used": 3, "balance": 15},
        },
        "EMP-AUTH": {"annual_error": "gaia_auth_failed"},
        "EMP-NET": {"annual_error": "gaia_unavailable"},
        "EMP-PART": {
            "annual_leave": {"mode": "flat", "quota": 5, "balance": None},
            "employment": {"social_service_year": "6"},
            "partial": True,
        },
    }


@pytest.fixture(scope="module")
def observations():
    return []


@pytest.fixture(scope="module")
def employee_server(observations):
    resolver = TrustedIdentityResolver({
        "user-alpha": "EMP-001",
        "user-beta": "EMP-002",
        "user-missing": "EMP-404",
        "user-auth": "EMP-AUTH",
        "user-network": "EMP-NET",
        "user-partial": "EMP-PART",
    }, ref_secret="employee-a2a-test-ref-secret")
    provider = StubEmployeeDataProvider(_records())
    agent = build_employee_data_agent(
        model_name=model_for("employee_data"),
        model_extra_config=extra_config_for("employee_data"),
    )
    runtime = EmployeeDataRuntime(
        identity_resolver=resolver,
        turn_runner=VeADKEmployeeDataTurnRunner(agent, provider),
        observer=observations.append,
    )
    server = uvicorn.Server(uvicorn.Config(
        build_a2a_app(runtime), host="127.0.0.1", port=8102, log_level="warning"
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", 8102)) == 0:
                break
        time.sleep(0.05)
    else:
        raise RuntimeError("Employee Data A2A服务未启动")
    yield runtime
    server.should_exit = True
    thread.join(timeout=15)
    assert not thread.is_alive()


@pytest.fixture(scope="module")
def evidence_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"employee-data-a2a-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    yield path
    print(f"\n[employee-data-a2a] 脱敏证据：{path}")


def _message(
    text: str,
    *,
    user_id="user-alpha",
    session_id: str | None = None,
    request_id: str | None = None,
    metadata_patch: dict | None = None,
) -> Message:
    session_id = session_id or f"employee-session-{uuid4()}"
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


async def _call(message: Message, *, streaming=False):
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


def _task(events) -> Task:
    tasks = [event[0] for event in events if isinstance(event, tuple)]
    assert tasks
    return tasks[-1]


def _data(task: Task) -> dict:
    assert task.artifacts
    for part in task.artifacts[-1].parts:
        if isinstance(part.root, DataPart):
            return part.root.data
    raise AssertionError("Employee Data Artifact缺少DataPart")


def _record(path: Path, case: str, result: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "case": case,
            "request_id": result.get("request_id"),
            "status": result.get("status"),
            "query_type": result.get("query_type"),
            "source": result.get("source"),
            "employee_ref": result.get("employee_ref"),
            "partial": result.get("partial"),
            "error_code": result.get("error_code"),
            "data_keys": sorted((result.get("data") or {}).keys()),
        }, ensure_ascii=False) + "\n")


@pytest.mark.asyncio
async def test_card_health_nonstream_and_balance(employee_server, evidence_path):
    request_id = str(uuid4())
    card, events = await _call(_message("我还有几天年假", request_id=request_id))
    result = _data(_task(events))
    assert card.name == "hr-employee-data-agent"
    assert card.protocol_version == "0.3.0"
    assert card.capabilities.streaming is True
    assert len(card.skills) == 3
    assert result["request_id"] == request_id
    assert result["status"] == "succeeded"
    assert result["source"] == "stub"
    assert result["data"]["leave_balance"]["remain"] == 4
    assert "EMP-001" not in str(result)
    _record(evidence_path, "leave_balance", result)


@pytest.mark.asyncio
async def test_sse_annual_calculation(employee_server, evidence_path):
    _, events = await _call(_message("我的年假怎么折算"), streaming=True)
    task = _task(events)
    result = _data(task)
    event_types = {type(event[1]).__name__ for event in events
                   if isinstance(event, tuple) and event[1] is not None}
    assert "TaskArtifactUpdateEvent" in event_types
    assert "TaskStatusUpdateEvent" in event_types
    assert task.status.state.value == "completed"
    assert result["data"]["annual_leave"]["quota"] == 5
    _record(evidence_path, "annual_calculation_sse", result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "query_type", "path", "value"),
    [
        ("我的医疗期余额", "medical_period", ("balance",), 21),
        ("我的参工信息", "employment_info", ("social_service_year",), "6"),
    ],
)
async def test_medical_and_employment(text, query_type, path, value, employee_server, evidence_path):
    _, events = await _call(_message(text))
    result = _data(_task(events))
    assert result["status"] == "succeeded"
    assert result["query_type"] == query_type
    current = result["data"]
    for segment in path:
        current = current[segment]
    assert current == value
    _record(evidence_path, query_type, result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "error_code"),
    [
        ("迟到扣款制度是什么", "policy_query_not_allowed"),
        ("明天请一天年假", "leave_request_not_allowed"),
        ("帮我查员工EMP-002的年假", "cross_employee_query_not_allowed"),
    ],
)
async def test_forbidden_responsibilities_are_rejected(
    text, error_code, employee_server, evidence_path
):
    _, events = await _call(_message(text))
    result = _data(_task(events))
    assert result["status"] == "rejected"
    assert result["error_code"] == error_code
    assert result["data"] is None
    _record(evidence_path, error_code, result)


@pytest.mark.asyncio
async def test_employee_id_metadata_is_protocol_error_before_runtime(
    employee_server, observations, caplog
):
    before = len(observations)
    secret = "EMP-MUST-NOT-LEAK"
    with pytest.raises(A2AClientError) as exc_info:
        await _call(_message("我还有几天年假", metadata_patch={"employeeId": secret}))
    assert len(observations) == before
    assert secret not in str(exc_info.value)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_unmapped_identity_is_rejected(employee_server, evidence_path):
    _, events = await _call(_message("我还有几天年假", user_id="unknown-user"))
    result = _data(_task(events))
    assert result["status"] == "rejected"
    assert result["error_code"] == "identity_unverified"
    assert result["employee_ref"] is None
    _record(evidence_path, "identity_unverified", result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "status", "error_code", "retryable"),
    [
        ("user-missing", "not_found", "employee_not_found", False),
        ("user-auth", "temporarily_unavailable", "gaia_auth_failed", True),
        ("user-network", "temporarily_unavailable", "gaia_unavailable", True),
    ],
)
async def test_employee_and_gaia_failures(
    user_id, status, error_code, retryable, employee_server, evidence_path
):
    _, events = await _call(_message("我还有几天年假", user_id=user_id))
    result = _data(_task(events))
    assert result["status"] == status
    assert result["error_code"] == error_code
    assert result["retryable"] is retryable
    assert result["source"] == "stub"
    assert result["data"] is None
    _record(evidence_path, error_code, result)


@pytest.mark.asyncio
async def test_partial_data_is_explicit(employee_server, evidence_path):
    _, events = await _call(_message(
        "我的年假怎么折算", user_id="user-partial"
    ))
    result = _data(_task(events))
    assert result["status"] == "succeeded"
    assert result["partial"] is True
    assert result["error_code"] == "partial_data"
    assert result["source"] == "stub"
    _record(evidence_path, "partial_data", result)


@pytest.mark.asyncio
async def test_missing_required_field_is_protocol_error(employee_server):
    message = _message("我还有几天年假")
    metadata = dict(message.metadata)
    del metadata["locale"]
    message.metadata = metadata
    with pytest.raises(A2AClientError):
        await _call(message)


@pytest.mark.asyncio
async def test_two_users_are_isolated(employee_server):
    _, alpha_events = await _call(_message("我还有几天年假", user_id="user-alpha"))
    _, beta_events = await _call(_message("我还有几天年假", user_id="user-beta"))
    alpha = _data(_task(alpha_events))
    beta = _data(_task(beta_events))
    assert alpha["data"]["leave_balance"]["remain"] == 4
    assert beta["data"]["leave_balance"]["remain"] == 8
    assert alpha["employee_ref"] != beta["employee_ref"]


@pytest.mark.asyncio
async def test_two_sessions_do_not_mix(employee_server):
    first_id = str(uuid4())
    second_id = str(uuid4())
    _, first_events = await _call(_message(
        "我的医疗期余额", session_id="employee-isolated-a", request_id=first_id
    ))
    _, second_events = await _call(_message(
        "我的医疗期余额", session_id="employee-isolated-b", request_id=second_id
    ))
    first = _data(_task(first_events))
    second = _data(_task(second_events))
    assert first["request_id"] == first_id
    assert second["request_id"] == second_id
    assert first["employee_ref"] == second["employee_ref"]


@pytest.mark.asyncio
async def test_official_client_gets_connection_failure_when_service_absent(employee_server):
    async with httpx.AsyncClient(timeout=0.5) as http:
        card = (await A2ACardResolver(http, BASE_URL).get_agent_card()).model_copy(
            update={"url": "http://127.0.0.1:8198/"}
        )
        client = ClientFactory(ClientConfig(
            streaming=False,
            httpx_client=http,
            supported_transports=["JSONRPC"],
        )).create(card)
        with pytest.raises(Exception):
            async for _ in client.send_message(_message("我还有几天年假")):
                pass
