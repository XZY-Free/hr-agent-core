"""官方A2A客户端的超时、鉴权与HTTP 500分类。"""

import httpx
import pytest

from packages.agent_runtime.a2a import client as client_module
from packages.agent_runtime.a2a.client import (
    A2AInvocationError,
    OfficialA2AClient,
    RemoteAgentSpec,
)
from packages.agent_runtime.a2a.context import A2ARequestContext


SPEC = RemoteAgentSpec(
    agent_name="hr-consult-agent",
    agent_version="1.0.0",
    allowed_statuses=frozenset({"succeeded"}),
    required_fields=frozenset(),
)
REQUEST = A2ARequestContext(
    request_id="request-a",
    user_id="user-a",
    session_id="session-a",
    caller_agent="hr_orchestrator",
    locale="zh-CN",
    message="迟到扣款制度是什么",
    context_summary="",
)


class FailingResolver:
    error = None

    def __init__(self, *args, **kwargs):
        pass

    async def get_agent_card(self):
        raise self.error


class RecordingAsyncClient:
    headers = None

    def __init__(self, *, timeout, headers=None):
        self.timeout = timeout
        RecordingAsyncClient.headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            httpx.ReadTimeout("timeout", request=httpx.Request("GET", "http://test")),
            "a2a_timeout",
        ),
        (
            httpx.HTTPStatusError(
                "unauthorized",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(401),
            ),
            "a2a_auth_failed",
        ),
        (
            httpx.HTTPStatusError(
                "server error",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(500),
            ),
            "a2a_unavailable",
        ),
    ],
    ids=["timeout", "authentication-failure", "http-500"],
)
async def test_transport_failures_are_classified_without_exposing_raw_error(
    monkeypatch, error, expected
):
    FailingResolver.error = error
    monkeypatch.setattr(client_module, "A2ACardResolver", FailingResolver)
    with pytest.raises(A2AInvocationError) as exc_info:
        await OfficialA2AClient(timeout_seconds=0.5).invoke(
            base_url="http://test", request=REQUEST, spec=SPEC
        )
    assert exc_info.value.error_code == expected
    assert str(error) not in str(exc_info.value)


@pytest.mark.asyncio
async def test_runtime_api_key_is_sent_only_as_authorization_header(monkeypatch):
    FailingResolver.error = httpx.ReadTimeout(
        "timeout",
        request=httpx.Request("GET", "https://consult.example.invalid"),
    )
    monkeypatch.setattr(client_module.httpx, "AsyncClient", RecordingAsyncClient)
    monkeypatch.setattr(client_module, "A2ACardResolver", FailingResolver)
    client = OfficialA2AClient(
        timeout_seconds=0.5,
        runtime_api_keys={"https://consult.example.invalid": "runtime-secret"},
    )

    with pytest.raises(A2AInvocationError):
        await client.invoke(
            base_url="https://consult.example.invalid/",
            request=REQUEST,
            spec=SPEC,
        )

    assert RecordingAsyncClient.headers == {
        "Authorization": "Bearer runtime-secret"
    }
    assert "runtime-secret" not in str(REQUEST.model_dump())
