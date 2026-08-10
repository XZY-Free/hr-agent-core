"""官方A2A客户端调用与通用Task/Artifact外壳校验。"""

from dataclasses import dataclass

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.types import DataPart, Message, Part, Role, Task, TextPart

from packages.agent_runtime.a2a.context import (
    A2ARequestContext,
    contains_sensitive_data,
)


class A2AInvocationError(RuntimeError):
    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__("远程Agent调用失败")


@dataclass(frozen=True)
class RemoteAgentSpec:
    agent_name: str
    agent_version: str
    allowed_statuses: frozenset[str]
    required_fields: frozenset[str]


@dataclass(frozen=True)
class A2AInvocationResult:
    data: dict
    task_state: str


class OfficialA2AClient:
    def __init__(self, *, timeout_seconds: float = 30):
        if timeout_seconds <= 0:
            raise ValueError("A2A超时必须大于0")
        self.timeout_seconds = timeout_seconds

    async def invoke(
        self,
        *,
        base_url: str,
        request: A2ARequestContext,
        spec: RemoteAgentSpec,
    ) -> A2AInvocationResult:
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
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as http:
                card = await A2ACardResolver(http, base_url).get_agent_card()
                if card.name != spec.agent_name or card.version != spec.agent_version:
                    raise A2AInvocationError("a2a_contract_error")
                client = ClientFactory(ClientConfig(
                    streaming=False,
                    httpx_client=http,
                    supported_transports=["JSONRPC"],
                )).create(card)
                events = []
                async for event in client.send_message(message):
                    events.append(event)
        except A2AInvocationError:
            raise
        except httpx.TimeoutException:
            raise A2AInvocationError("a2a_timeout") from None
        except httpx.HTTPStatusError as exc:
            code = "a2a_auth_failed" if exc.response.status_code in {401, 403} else "a2a_unavailable"
            raise A2AInvocationError(code) from None
        except Exception:
            raise A2AInvocationError("a2a_unavailable") from None

        tasks = [event[0] for event in events if isinstance(event, tuple)]
        if not tasks or not isinstance(tasks[-1], Task):
            raise A2AInvocationError("a2a_contract_error")
        return validate_task_result(tasks[-1], request=request, spec=spec)


def validate_task_result(
    task: Task,
    *,
    request: A2ARequestContext,
    spec: RemoteAgentSpec,
) -> A2AInvocationResult:
    """校验官方Task及最后一个Artifact，并只返回白名单业务数据。"""
    if not task.artifacts:
        raise A2AInvocationError("a2a_contract_error")
    data = None
    for part in task.artifacts[-1].parts:
        if isinstance(part.root, DataPart):
            data = part.root.data
            break
    if not isinstance(data, dict):
        raise A2AInvocationError("a2a_contract_error")
    if contains_sensitive_data(data):
        raise A2AInvocationError("a2a_security_error")
    if not spec.required_fields <= set(data):
        raise A2AInvocationError("a2a_contract_error")
    if data.get("agent_name") != spec.agent_name:
        raise A2AInvocationError("a2a_contract_error")
    if data.get("agent_version") != spec.agent_version:
        raise A2AInvocationError("a2a_contract_error")
    if data.get("request_id") != request.request_id:
        raise A2AInvocationError("a2a_contract_error")
    if data.get("status") not in spec.allowed_statuses:
        raise A2AInvocationError("a2a_contract_error")
    state = task.status.state.value
    expected_states = {
        "succeeded": {"completed"},
        "not_found": {"completed"},
        "need_more_information": {"input-required"},
        "rejected": {"rejected"},
        "temporarily_unavailable": {"failed"},
        "failed": {"failed"},
    }
    if state not in expected_states.get(data["status"], set()):
        raise A2AInvocationError("a2a_contract_error")
    return A2AInvocationResult(data=data, task_state=state)
