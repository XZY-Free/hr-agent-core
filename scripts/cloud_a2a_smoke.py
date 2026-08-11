"""Authenticated cloud A2A smoke test with redacted output."""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.types import DataPart, Message, Part, Role, Task, TextPart


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


async def run() -> dict[str, object]:
    base_url = _required("RUNTIME_URL").rstrip("/")
    api_key = _required("RUNTIME_API_KEY")
    kind = _required("AGENT_KIND")
    if kind not in {"consult", "employee"}:
        raise SystemExit("AGENT_KIND must be consult or employee")
    request_id = str(uuid4())
    session_id = str(uuid4())
    user_id = os.environ.get("A2A_USER_ID", "cloud-a2a-user-a")
    message_text = "迟到扣款制度是什么" if kind == "consult" else "我还有几天年假"
    message = Message(
        role=Role.user,
        message_id=request_id,
        context_id=session_id,
        metadata={
            "request_id": request_id,
            "user_id": user_id,
            "session_id": session_id,
            "caller_agent": "hr_orchestrator",
            "locale": "zh-CN",
            "context_summary": "",
        },
        parts=[Part(root=TextPart(text=message_text))],
    )
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"}, timeout=180
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
        raise SystemExit("A2A Task is unavailable")
    task = tasks[-1]
    if not task.artifacts:
        raise SystemExit("A2A Artifact is unavailable")
    data = None
    has_text_part = False
    for part in task.artifacts[-1].parts:
        has_text_part = has_text_part or isinstance(part.root, TextPart)
        if isinstance(part.root, DataPart):
            data = part.root.data
    if not isinstance(data, dict):
        raise SystemExit("A2A DataPart is unavailable")
    if data.get("request_id") != request_id:
        raise SystemExit("A2A request_id mismatch")

    result: dict[str, object] = {
        "agent_name": card.name,
        "agent_version": card.version,
        "request_id": request_id,
        "status": data.get("status"),
        "task_state": task.status.state.value,
        "text_part": has_text_part,
        "data_part": True,
    }
    if kind == "consult":
        sources = data.get("sources")
        if data.get("status") != "succeeded" or not isinstance(sources, list) or not sources:
            raise SystemExit("Consult Viking result is unavailable")
        result.update({
            "source_count": len(sources),
            "source_fields_valid": all(
                isinstance(row, dict)
                and isinstance(row.get("source"), str)
                and bool(row.get("source"))
                and isinstance(row.get("score"), (int, float))
                and not isinstance(row.get("score"), bool)
                for row in sources
            ),
        })
    else:
        if data.get("status") != "succeeded" or data.get("source") != "stub":
            raise SystemExit("Employee Data Stub result is unavailable")
        serialized = json.dumps(data, ensure_ascii=False)
        result.update({
            "source_is_stub": True,
            "employee_ref_present": bool(data.get("employee_ref")),
            "raw_employee_id_absent": "EMP-" not in serialized,
        })
    return result


def main() -> None:
    print(json.dumps(asyncio.run(run()), sort_keys=True))


if __name__ == "__main__":
    main()
