"""Collect redacted, layered evidence for the six frozen cloud failures.

Runtime URLs and API keys are read only from the process environment. The
script never prints either value and never serializes credentials to evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import yaml
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.types import DataPart, Message, Part, Role, Task, TextPart

from apps.orchestrator.a2a.router import CONSULT_SPEC, EMPLOYEE_SPEC
from packages.agent_runtime.a2a.client import OfficialA2AClient
from packages.agent_runtime.a2a.context import A2ARequestContext


REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "tests" / "eval" / "cases.yaml"
LOG_DIR = REPO_ROOT / "tests" / "e2e" / "logs"
CASE_IDS = {
    "quick_tomorrow",
    "gender_mismatch",
    "rest_day",
    "balance_query",
    "personal_data_not_kb",
    "doc_qa",
}
DUMMY_STATE = {
    "employeeId": "E001",
    "corp_id": "corp1",
    "client_secret": "sec",
    "grant_type": "client_credentials",
}
DOC_QA_CONTEXT = {
    "url": "https://example.com/notice.docx",
    "content": (
        "# 2026 年春节假期安排通知\n\n"
        "一、放假时间：2 月 16 日至 2 月 22 日，共 7 天。\n"
        "二、值班安排：各部门自行排定并于 2 月 10 日前备案。\n"
        "三、考勤要求：节前与节后工作日正常打卡。\n"
    ),
}
_SENSITIVE_KEYS = re.compile(
    r"secret|authorization|api.?key|access.?key|employee.?id|corp.?id|token|jwt",
    re.IGNORECASE,
)


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _resolve_dates(text: str) -> str:
    today = date.today()
    for token, offset in {
        "<today>": 0,
        "<tomorrow>": 1,
        "<yesterday>": -1,
        "<rest_day>": -2,
    }.items():
        text = text.replace(token, (today + timedelta(days=offset)).isoformat())
    return text


def _safe(value):
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if _SENSITIVE_KEYS.search(str(key)) else _safe(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, str) and re.search(r"bearer\s+", value, re.IGNORECASE):
        return "<redacted>"
    return value


def _events(response: httpx.Response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                events.append(json.loads(payload))
    return events


def _turn(client, base_url: str, user_id: str, session_id: str, message: str) -> dict:
    response = client.post(
        base_url + "/run_sse",
        json={
            "app_name": "root_agent",
            "user_id": user_id,
            "session_id": session_id,
            "new_message": {"role": "user", "parts": [{"text": message}]},
            "streaming": True,
        },
    )
    events = _events(response)
    final_event_texts: list[str] = []
    partial_texts: list[str] = []
    all_texts: list[str] = []
    tools: list[dict] = []
    for event in events:
        event_texts = []
        for part in (event.get("content") or {}).get("parts", []):
            if not isinstance(part, dict):
                continue
            call = part.get("functionCall") or part.get("function_call")
            if isinstance(call, dict) and call.get("name"):
                tools.append({"kind": "call", "name": call["name"], "payload": _safe(call.get("args") or {})})
            result = part.get("functionResponse") or part.get("function_response")
            if isinstance(result, dict) and result.get("name"):
                tools.append({
                    "kind": "result",
                    "name": result["name"],
                    "payload": _safe(result.get("response") or {}),
                })
            text = part.get("text")
            if isinstance(text, str) and text and not part.get("thought"):
                event_texts.append(text)
                all_texts.append(text)
        if event_texts:
            if event.get("partial"):
                partial_texts.extend(event_texts)
            else:
                final_event_texts = event_texts
    final_text = "\n".join(final_event_texts) or "".join(partial_texts)
    return {
        "http_status": response.status_code,
        "event_count": len(events),
        "tool_steps": tools,
        "final_answer": final_text,
        "all_non_thought_text": "\n".join(all_texts),
        "last_event_answer": "\n".join(final_event_texts),
        "sse_final_equals_aggregate": final_text == ("\n".join(final_event_texts) or "".join(partial_texts)),
        "remote": next((event.get("a2a") for event in events if event.get("a2a")), None),
    }


async def _raw_a2a(base_url: str, api_key: str, request: A2ARequestContext) -> dict:
    message = Message(
        role=Role.user,
        message_id=request.request_id,
        context_id=request.session_id,
        metadata={
            "request_id": request.request_id,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "caller_agent": request.caller_agent,
            "locale": request.locale,
            "context_summary": request.context_summary,
        },
        parts=[Part(root=TextPart(text=request.message))],
    )
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"}, timeout=240
    ) as http:
        card = await A2ACardResolver(http, base_url).get_agent_card()
        client = ClientFactory(ClientConfig(
            streaming=False,
            httpx_client=http,
            supported_transports=["JSONRPC"],
        )).create(card)
        events = [event async for event in client.send_message(message)]
    tasks = [event[0] for event in events if isinstance(event, tuple)]
    if not tasks or not isinstance(tasks[-1], Task):
        return {"task_present": False}
    task = tasks[-1]
    data = None
    has_text = False
    if task.artifacts:
        for part in task.artifacts[-1].parts:
            has_text = has_text or isinstance(part.root, TextPart)
            if isinstance(part.root, DataPart):
                data = part.root.data
    return {
        "task_present": True,
        "task_state": task.status.state.value,
        "artifact_present": bool(task.artifacts),
        "text_part": has_text,
        "data_part": _safe(data) if isinstance(data, dict) else None,
    }


async def _remote_layers(
    *, kind: str, base_url: str, api_key: str, user_id: str, message: str
) -> dict:
    request = A2ARequestContext(
        request_id=str(uuid4()),
        user_id=user_id,
        session_id=str(uuid4()),
        caller_agent="hr_orchestrator",
        locale="zh-CN",
        message=message,
        context_summary="",
    )
    raw = await _raw_a2a(base_url, api_key, request)
    parsed = None
    parsed_error = None
    try:
        result = await OfficialA2AClient(
            timeout_seconds=240,
            runtime_api_keys={base_url: api_key},
        ).invoke(
            base_url=base_url,
            request=request,
            spec=CONSULT_SPEC if kind == "consult" else EMPLOYEE_SPEC,
        )
        parsed = _safe(result.data)
    except Exception as exc:  # Only the exception type is evidence; never serialize its text.
        parsed_error = type(exc).__name__
    return {
        "request_id": request.request_id,
        "artifact": raw,
        "client_parsed": parsed,
        "client_error_type": parsed_error,
    }


async def _run() -> tuple[list[dict], Path]:
    orchestrator_url = _required("ORCHESTRATOR_RUNTIME_URL").rstrip("/")
    orchestrator_key = _required("ORCHESTRATOR_RUNTIME_API_KEY")
    consult_url = _required("CONSULT_RUNTIME_URL").rstrip("/")
    consult_key = _required("CONSULT_RUNTIME_API_KEY")
    employee_url = _required("EMPLOYEE_RUNTIME_URL").rstrip("/")
    employee_key = _required("EMPLOYEE_RUNTIME_API_KEY")
    user_id = os.environ.get("ORCHESTRATOR_USER_ID", "cloud-a2a-user-a")
    cases = [case for case in yaml.safe_load(CASES_PATH.read_text()) if case["id"] in CASE_IDS]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = LOG_DIR / f"cloud-six-layer-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    records = []
    headers = {"Authorization": f"Bearer {orchestrator_key}"}
    with httpx.Client(headers=headers, timeout=240) as client:
        for case in cases:
            session_id = f"diag-{case['id']}-{uuid4()}"
            state = dict(DUMMY_STATE)
            if case["id"] == "doc_qa":
                state["document_context"] = DOC_QA_CONTEXT
            created = client.post(
                f"{orchestrator_url}/apps/root_agent/users/{user_id}/sessions",
                json={"session_id": session_id, "state": state},
            )
            turns = []
            for message in case["turns"] if created.status_code < 300 else []:
                turns.append(_turn(
                    client, orchestrator_url, user_id, session_id, _resolve_dates(message)
                ))
            record = {
                "case_id": case["id"],
                "test_identity": "fixture-user-a",
                "session_create_status": created.status_code,
                "session_state_initialized": created.status_code < 300,
                "session_state_keys": sorted(state),
                "process_date": date.today().isoformat(),
                "resolved_inputs": [_resolve_dates(message) for message in case["turns"]],
                "route_targets": [
                    (turn.get("remote") or {}).get("target", "local") for turn in turns
                ],
                "turns": turns,
            }
            if case["id"] in {"balance_query", "personal_data_not_kb"}:
                record["remote_layers"] = await _remote_layers(
                    kind="employee",
                    base_url=employee_url,
                    api_key=employee_key,
                    user_id=user_id,
                    message=_resolve_dates(case["turns"][0]),
                )
                record["orchestrator_model_layer"] = "not_applicable_direct_a2a_middleware"
            elif case["id"] == "doc_qa":
                record["remote_layers"] = await _remote_layers(
                    kind="consult",
                    base_url=consult_url,
                    api_key=consult_key,
                    user_id=user_id,
                    message=case["turns"][0],
                )
            records.append(record)
            with evidence_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            print(json.dumps({
                "case_id": case["id"],
                "session_status": created.status_code,
                "target_count": len(record["route_targets"]),
                "remote_layer_captured": "remote_layers" in record,
            }, sort_keys=True), flush=True)
    return records, evidence_path


def main() -> None:
    records, evidence = asyncio.run(_run())
    print(json.dumps({
        "case_count": len(records),
        "evidence_file": evidence.name,
        "secret_values_serialized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
