"""官方A2A客户端调用与通用Task/Artifact外壳校验。"""

from dataclasses import dataclass
import asyncio

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.types import DataPart, Message, Part, Role, Task, TaskIdParams, TaskQueryParams, TaskState, TextPart
from packages.agent_runtime.a2a.cancellable_executor import TaskCancellationError

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
    task_id: str
    context_id: str


class OfficialA2AClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30,
        runtime_api_keys: dict[str, str] | None = None,
    ):
        if timeout_seconds <= 0:
            raise ValueError("A2A超时必须大于0")
        self.timeout_seconds = timeout_seconds
        self.runtime_api_keys = {
            base_url.rstrip("/"): api_key
            for base_url, api_key in (runtime_api_keys or {}).items()
            if base_url.strip() and api_key.strip()
        }

    async def invoke(
        self,
        *,
        base_url: str,
        request: A2ARequestContext,
        spec: RemoteAgentSpec,
        task_id: str | None = None,
    ) -> A2AInvocationResult:
        message = Message(
            role=Role.user,
            message_id=request.request_id,
            context_id=request.session_id,
            task_id=task_id,
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
            api_key = self.runtime_api_keys.get(base_url.rstrip("/"))
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers=headers,
            ) as http:
                card = await A2ACardResolver(http, base_url).get_agent_card()
                if card.name != spec.agent_name or card.version != spec.agent_version:
                    raise A2AInvocationError("a2a_contract_error")
                client = ClientFactory(ClientConfig(
                    streaming=True,
                    httpx_client=http,
                    supported_transports=["JSONRPC"],
                )).create(card)
                events = []
                latest_task = None
                task_known = asyncio.Event()

                async def consume():
                    nonlocal latest_task
                    try:
                        async for event in client.send_message(message):
                            events.append(event)
                            if isinstance(event, tuple) and isinstance(event[0], Task):
                                latest_task = event[0]
                                task_known.set()
                    finally:
                        task_known.set()

                receiving = asyncio.create_task(consume())
                try:
                    await asyncio.shield(receiving)
                except asyncio.CancelledError:
                    # 保持接收器存活，先获得远端task id，再取消远端而不只是断开HTTP。
                    try:
                        await asyncio.wait_for(task_known.wait(), self.timeout_seconds)
                        if latest_task is None:
                            raise TaskCancellationError()
                        terminal = {TaskState.completed, TaskState.failed, TaskState.rejected, TaskState.canceled}
                        if latest_task.status.state not in terminal:
                            await self._stop_task(client, latest_task.id, latest_task.context_id,
                                                  allowed_states=terminal)
                    except Exception:
                        raise TaskCancellationError() from None
                    finally:
                        receiving.cancel()
                        await asyncio.gather(receiving, return_exceptions=True)
                    raise
        except TaskCancellationError:
            raise
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

    @staticmethod
    async def _stop_task(client, task_id: str, context_id: str, *, allowed_states: set):
        try:
            stopped = await client.cancel_task(TaskIdParams(id=task_id))
        except Exception:
            # ACK丢失或与完成竞争：查询原任务核实，不能把其他任务的终态当证据。
            stopped = await client.get_task(TaskQueryParams(id=task_id))
        if (stopped.id != task_id or stopped.context_id != context_id
                or stopped.status.state not in allowed_states):
            raise TaskCancellationError()

    async def cancel_task(self, *, base_url: str, spec: RemoteAgentSpec,
                          task_id: str, context_id: str) -> None:
        api_key = self.runtime_api_keys.get(base_url.rstrip("/"))
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as http:
                card = await A2ACardResolver(http, base_url).get_agent_card()
                if card.name != spec.agent_name or card.version != spec.agent_version:
                    raise TaskCancellationError()
                client = ClientFactory(ClientConfig(httpx_client=http,
                    supported_transports=["JSONRPC"])).create(card)
                await self._stop_task(client, task_id, context_id,
                                     allowed_states={TaskState.canceled})
        except Exception:
            raise TaskCancellationError() from None


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
    return A2AInvocationResult(data=data, task_state=state,
                               task_id=task.id, context_id=task.context_id)
