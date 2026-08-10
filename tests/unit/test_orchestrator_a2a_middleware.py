"""Orchestrator的/run_sse显式A2A拦截与本地透传。"""

import json
from dataclasses import dataclass

import httpx
import pytest

from apps.orchestrator.a2a.middleware import DeterministicA2AMiddleware
from apps.orchestrator.a2a.router import RemoteRouteResponse


@dataclass
class FakeRouter:
    response: RemoteRouteResponse | None

    def __post_init__(self):
        self.payloads = []

    async def route(self, payload):
        self.payloads.append(payload)
        return self.response


class LocalApp:
    def __init__(self):
        self.bodies = []

    async def __call__(self, scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        self.bodies.append(body)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"local"})


def _payload(text: str):
    return {
        "user_id": "user-a",
        "session_id": "session-a",
        "new_message": {"role": "user", "parts": [{"text": text}]},
    }


@pytest.mark.asyncio
async def test_remote_route_returns_single_safe_sse_event_without_local_execution():
    local = LocalApp()
    router = FakeRouter(RemoteRouteResponse(
        answer="远程结果",
        request_id="request-a",
        target="hr-consult-agent",
        status="succeeded",
    ))
    app = DeterministicA2AMiddleware(local, router=router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/run_sse", json=_payload("迟到扣款制度是什么"))
    assert response.status_code == 200
    event = json.loads(response.text.removeprefix("data: ").strip())
    assert event["content"]["parts"] == [{"text": "远程结果"}]
    assert event["a2a"] == {
        "target": "hr-consult-agent",
        "status": "succeeded",
        "request_id": "request-a",
        "error_code": None,
    }
    assert local.bodies == []


@pytest.mark.asyncio
async def test_local_route_replays_original_body_unchanged():
    local = LocalApp()
    router = FakeRouter(None)
    app = DeterministicA2AMiddleware(local, router=router)
    payload = _payload("明天请一天年假")
    raw = json.dumps(payload, ensure_ascii=False).encode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run_sse", content=raw, headers={"content-type": "application/json"}
        )
    assert response.text == "local"
    assert local.bodies == [raw]
