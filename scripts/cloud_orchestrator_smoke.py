"""Authenticated Orchestrator health, session, SSE, and JUMP smoke test."""

from __future__ import annotations

import json
import os
import re
from uuid import uuid4

import httpx


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _sse_events(response: httpx.Response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                events.append(json.loads(payload))
    return events


def main() -> None:
    base_url = _required("RUNTIME_URL").rstrip("/")
    api_key = _required("RUNTIME_API_KEY")
    user_id = os.environ.get("ORCHESTRATOR_USER_ID", "cloud-a2a-user-a")
    session_id = str(uuid4())
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(headers=headers, timeout=180) as client:
        health = client.get(base_url + "/health")
        session = client.post(
            f"{base_url}/apps/root_agent/users/{user_id}/sessions",
            json={"session_id": session_id, "state": {}},
        )
        sse = client.post(
            base_url + "/run_sse",
            json={
                "app_name": "root_agent",
                "user_id": user_id,
                "session_id": session_id,
                "new_message": {
                    "role": "user",
                    "parts": [{"text": "打开打卡明细"}],
                },
                "streaming": True,
            },
        )
    events = _sse_events(sse)
    text = "\n".join(
        part.get("text", "")
        for event in events
        for part in (event.get("content") or {}).get("parts", [])
        if isinstance(part, dict) and not part.get("thought")
    )
    request_ids = sorted({
        value
        for event in events
        for value in [event.get("request_id"), (event.get("a2a") or {}).get("request_id")]
        if isinstance(value, str) and value
    })
    result = {
        "health_http_status": health.status_code,
        "session_http_status": session.status_code,
        "sse_http_status": sse.status_code,
        "sse_event_count": len(events),
        "jump_marker_present": bool(re.search(r"\[\[JUMP:punch-details\]\]", text)),
        "remote_a2a_absent": not any(event.get("a2a") for event in events),
        "request_ids": request_ids,
    }
    print(json.dumps(result, sort_keys=True))
    if not (
        health.status_code == 200
        and session.status_code < 300
        and sse.status_code == 200
        and events
        and result["jump_marker_present"]
        and result["remote_a2a_absent"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
