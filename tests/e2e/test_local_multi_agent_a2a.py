"""8101/8102/8000三服务的本地显式A2A闭环。"""

import json
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import requests
import uvicorn

from agent import build_agent_application
from apps.consult_agent.a2a.server import build_a2a_app as build_consult_app
from apps.consult_agent.runtime import build_consult_runtime
from apps.employee_data_agent.a2a.server import build_a2a_app as build_employee_app
from apps.employee_data_agent.agent import build_employee_data_agent
from apps.employee_data_agent.identity import TrustedIdentityResolver
from apps.employee_data_agent.provider import StubEmployeeDataProvider
from apps.employee_data_agent.runtime import EmployeeDataRuntime, VeADKEmployeeDataTurnRunner
from packages.agent_runtime.model_config import extra_config_for, model_for
from packages.hr_domain.gaia import client as gaia_client_module
from tests.eval import test_eval as local_eval


BASE_URL = "http://127.0.0.1:8000"
LOG_DIR = Path(__file__).with_name("logs")
DUMMY_KEY = "dummy-for-struct-test-only"


def _has_real_config() -> bool:
    required = (
        "MODEL_AGENT_API_KEY", "VOLCENGINE_ACCESS_KEY", "VOLCENGINE_SECRET_KEY",
        "KB_COLLECTION_POLICY", "KB_COLLECTION_HANDBOOK",
        "KB_COLLECTION_SALARY", "KB_COLLECTION_CHILDCARE",
    )
    return (
        os.getenv("RUN_REAL_MULTI_AGENT_A2A_TESTS") == "true"
        and os.getenv("MODEL_AGENT_API_KEY") != DUMMY_KEY
        and os.getenv("KB_BACKEND") == "agentkit"
        and all(os.getenv(name, "").strip() for name in required)
    )


pytestmark = [
    pytest.mark.integration,
    pytest.mark.a2a,
    pytest.mark.multi_agent_a2a,
    pytest.mark.skipif(
        not _has_real_config(),
        reason="需RUN_REAL_MULTI_AGENT_A2A_TESTS=true及真实模型/Viking配置",
    ),
]


def _employee_records():
    return {
        "EMP-001": {
            "annual_leave": {
                "mode": "flat", "quota": 5,
                "balance": [{
                    "leave_name": "年休假", "total": 5, "used": 1, "remain": 4,
                }],
            },
            "employment": {
                "social_service_year": "6", "social_service_month": "4",
                "social_service_day": "0", "hire_month": "11", "hire_day": "03",
            },
            "medical_period": {"quota": 24, "used": 3, "balance": 21},
        }
    }


def _wait_for_port(port: int) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"本地测试端口未就绪：{port}")


@pytest.fixture(scope="module")
def multi_agent_stack():
    consult_observations = []
    employee_observations = []
    consult_runtime = build_consult_runtime(observer=consult_observations.append)
    employee_agent = build_employee_data_agent(
        model_name=model_for("employee_data"),
        model_extra_config=extra_config_for("employee_data"),
    )
    employee_runtime = EmployeeDataRuntime(
        identity_resolver=TrustedIdentityResolver(
            {"eval-user": "EMP-001", "eval-user-b": "EMP-001"},
            ref_secret="local-multi-agent-test-ref-secret",
        ),
        turn_runner=VeADKEmployeeDataTurnRunner(
            employee_agent, StubEmployeeDataProvider(_employee_records())
        ),
        observer=employee_observations.append,
    )
    orchestrator = build_agent_application(
        consult_transport="a2a", employee_data_transport="a2a"
    )
    servers = [
        uvicorn.Server(uvicorn.Config(
            build_consult_app(consult_runtime),
            host="127.0.0.1", port=8101, log_level="warning",
        )),
        uvicorn.Server(uvicorn.Config(
            build_employee_app(employee_runtime),
            host="127.0.0.1", port=8102, log_level="warning",
        )),
        uvicorn.Server(uvicorn.Config(
            orchestrator.agent_server_app.app,
            host="127.0.0.1", port=8000, log_level="warning",
        )),
    ]
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        for port in (8101, 8102, 8000):
            _wait_for_port(port)
        yield {
            "consult_observations": consult_observations,
            "employee_observations": employee_observations,
        }
    finally:
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()


@pytest.fixture(autouse=True)
def external_stubs(monkeypatch):
    """本地Leave沿用既有Gaia桩；文档下载沿用既有通知桩。"""
    monkeypatch.setattr(
        gaia_client_module.GaiaClient, "request", local_eval._stub_request
    )
    import apps.consult_agent.tools.parse_document as parse_document_module

    monkeypatch.setattr(
        parse_document_module.requests,
        "get",
        lambda *args, **kwargs: local_eval._FakeResp(),
    )


@pytest.fixture(scope="module")
def evidence_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"local-multi-agent-a2a-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    yield path
    print(f"\n[local-multi-agent-a2a] 脱敏证据：{path}")


def _create_session(session_id: str, *, user_id: str = "eval-user") -> None:
    response = requests.post(
        f"{BASE_URL}/apps/root_agent/users/{user_id}/sessions",
        json={"session_id": session_id, "state": local_eval.BIZ_STATE},
        timeout=30,
    )
    response.raise_for_status()


def _run_sse(text: str, *, session_id: str, user_id: str = "eval-user") -> dict:
    response = requests.post(
        f"{BASE_URL}/run_sse",
        json={
            "app_name": "root_agent", "user_id": user_id,
            "session_id": session_id,
            "new_message": {"role": "user", "parts": [{"text": text}]},
            "streaming": True,
        },
        stream=True,
        timeout=180,
    )
    response.raise_for_status()
    events = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    assert events
    partial_text_parts = []
    final_text = ""
    tool_names = []
    for event in events:
        event_text_parts = []
        for part in (event.get("content") or {}).get("parts", []):
            value = part.get("text")
            if value and not part.get("thought"):
                event_text_parts.append(value)
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, dict) and function_call.get("name"):
                tool_names.append(function_call["name"])
        if event_text_parts:
            if event.get("partial"):
                partial_text_parts.extend(event_text_parts)
            else:
                final_text = "\n".join(event_text_parts)
    remote = next((event.get("a2a") for event in events if event.get("a2a")), None)
    all_event_text = "\n".join(
        part.get("text", "")
        for event in events
        for part in (event.get("content") or {}).get("parts", [])
        if isinstance(part, dict)
    )
    for marker in dict.fromkeys(re.findall(r"\[\[JUMP:[a-z-]+\]\]", all_event_text)):
        if marker not in final_text:
            final_text = f"{final_text}\n{marker}".strip()
    return {
        "events": events, "text": final_text or "".join(partial_text_parts),
        "tools": tool_names, "remote": remote,
    }


def _remote_tools(result: dict, stack: dict) -> list[str]:
    remote = result["remote"]
    if not remote:
        return []
    observations = (
        stack["consult_observations"]
        if remote["target"] == "hr-consult-agent"
        else stack["employee_observations"]
    )
    matched = [row for row in observations if row.request_id == remote["request_id"]]
    assert len(matched) == 1
    if remote["target"] == "hr-consult-agent":
        return list(matched[0].tool_names)
    return [matched[0].tool_name]


def _record(path: Path, *, case_id: str, result: dict, tools: list[str]) -> None:
    remote = result["remote"] or {}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "case": case_id,
            "target": remote.get("target", "local"),
            "request_id": remote.get("request_id"),
            "status": remote.get("status", "local"),
            "error_code": remote.get("error_code"),
            "tools": tools,
            "jump": "[[JUMP:" in result["text"],
        }, ensure_ascii=False) + "\n")


FIXED_ROUTES = [
    ("迟到扣款制度是什么", "hr-consult-agent", "扣"),
    ("四川育儿假有几天", "hr-consult-agent", "10"),
    ("育儿假有几天", "hr-consult-agent", "省"),
    ("我还有几天年假", "hr-employee-data-agent", "4"),
    ("我的医疗期余额", "hr-employee-data-agent", "21"),
    ("我的年假怎么折算", "hr-employee-data-agent", "5"),
    ("明天请一天年假", "local", "年休假"),
    ("打开打卡明细", "local", "[[JUMP:punch-details]]"),
    ("取消昨天的请假", "local", "[[JUMP:my-forms]]"),
    ("转人工", "local", "转接"),
]


@pytest.mark.parametrize(
    ("message", "target", "keyword"), FIXED_ROUTES,
    ids=[f"fixed-{index}" for index in range(len(FIXED_ROUTES))],
)
def test_fixed_end_to_end_routes(
    message, target, keyword, multi_agent_stack, evidence_path
):
    session_id = f"fixed-{uuid4()}"
    _create_session(session_id)
    result = _run_sse(message, session_id=session_id)
    actual_target = result["remote"]["target"] if result["remote"] else "local"
    assert actual_target == target
    assert keyword in result["text"]
    tools = result["tools"] + _remote_tools(result, multi_agent_stack)
    _record(evidence_path, case_id=message, result=result, tools=tools)


def test_same_session_followup_stays_with_consult(multi_agent_stack, evidence_path):
    session_id = f"followup-{uuid4()}"
    _create_session(session_id)
    first = _run_sse("育儿假有几天", session_id=session_id)
    second = _run_sse("四川", session_id=session_id)
    assert first["remote"]["target"] == "hr-consult-agent"
    assert first["remote"]["status"] == "need_more_information"
    assert second["remote"]["target"] == "hr-consult-agent"
    assert "10" in second["text"]
    _record(
        evidence_path, case_id="same-session-consult-followup", result=second,
        tools=_remote_tools(second, multi_agent_stack),
    )


def test_different_sessions_can_run_concurrently(multi_agent_stack, evidence_path):
    session_a = f"concurrent-a-{uuid4()}"
    session_b = f"concurrent-b-{uuid4()}"
    _create_session(session_a, user_id="eval-user")
    _create_session(session_b, user_id="eval-user-b")
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(
            _run_sse, "迟到扣款制度是什么", session_id=session_a,
            user_id="eval-user",
        )
        future_b = executor.submit(
            _run_sse, "我还有几天年假", session_id=session_b,
            user_id="eval-user-b",
        )
        result_a = future_a.result(timeout=180)
        result_b = future_b.result(timeout=180)
    assert result_a["remote"]["target"] == "hr-consult-agent"
    assert result_b["remote"]["target"] == "hr-employee-data-agent"
    assert result_a["remote"]["request_id"] != result_b["remote"]["request_id"]
    assert "4" in result_b["text"]
    _record(
        evidence_path, case_id="concurrent-consult", result=result_a,
        tools=_remote_tools(result_a, multi_agent_stack),
    )
    _record(
        evidence_path, case_id="concurrent-employee", result=result_b,
        tools=_remote_tools(result_b, multi_agent_stack),
    )


@pytest.mark.a2a_eval
@pytest.mark.parametrize(
    "case", local_eval.CASES, ids=[case["id"] for case in local_eval.CASES]
)
def test_root_core_eval_in_a2a_mode(case, multi_agent_stack, evidence_path):
    session_id = f"a2a-eval-{case['id']}-{uuid4()}"
    _create_session(session_id)
    tool_names = []
    all_texts = []
    final_text = ""
    for turn in case["turns"]:
        result = _run_sse(local_eval._resolve_dates(turn), session_id=session_id)
        final_text = result["text"]
        all_texts.append(final_text)
        turn_tools = result["tools"] + _remote_tools(result, multi_agent_stack)
        tool_names.extend(turn_tools)
        _record(
            evidence_path, case_id=case["id"], result=result, tools=turn_tools
        )
    local_eval._assert_case(case, tool_names, final_text, "\n".join(all_texts))


def test_health_session_sse_and_jump(multi_agent_stack):
    health = requests.get(f"{BASE_URL}/health", timeout=30)
    assert health.status_code == 200
    session_id = f"health-{uuid4()}"
    _create_session(session_id)
    result = _run_sse("打开打卡明细", session_id=session_id)
    assert result["events"]
    assert "[[JUMP:punch-details]]" in result["text"]
    assert result["remote"] is None


def test_missing_session_never_calls_remote_agent(multi_agent_stack):
    before_consult = len(multi_agent_stack["consult_observations"])
    before_employee = len(multi_agent_stack["employee_observations"])
    response = requests.post(
        f"{BASE_URL}/run_sse",
        json={
            "app_name": "root_agent",
            "user_id": "eval-user",
            "session_id": f"missing-{uuid4()}",
            "new_message": {
                "role": "user",
                "parts": [{"text": "迟到扣款制度是什么"}],
            },
            "streaming": True,
        },
        timeout=30,
    )
    assert response.status_code >= 400 or "Session not found" in response.text
    assert '"a2a"' not in response.text
    assert len(multi_agent_stack["consult_observations"]) == before_consult
    assert len(multi_agent_stack["employee_observations"]) == before_employee
