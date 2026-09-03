"""通过真实 HTTP 和官方 SDK 验证上游取消会停止下游工作，不是断开连接。"""

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn

from apps.consult_agent.a2a.card import build_agent_card
from apps.consult_agent.a2a.executor import ConsultAgentExecutor
from packages.agent_runtime.a2a.client import OfficialA2AClient, RemoteAgentSpec
from packages.agent_runtime.a2a.context import A2ARequestContext
from packages.agent_runtime.a2a.server import build_jsonrpc_app
from packages.agent_runtime.a2a.cancellable_executor import TaskCancellationError
from starlette.responses import JSONResponse


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [None, "id", "contextId"])
async def test_cancel_is_forwarded_to_downstream_and_waits_for_cleanup(corrupt):
    class Work:
        def __init__(self):
            self.started = asyncio.Event()
            self.stopped = asyncio.Event()

        async def run(self, request):
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.02)
                self.stopped.set()

    runtime = Work()
    executor = ConsultAgentExecutor(runtime)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = build_jsonrpc_app(agent_card=build_agent_card(base_url), agent_executor=executor,
                            title="cancel-test", health={})
    @app.middleware("http")
    async def corrupt_cancel_response(request, call_next):
        payload = await request.json() if request.method == "POST" else {}
        response = await call_next(request)
        if corrupt and payload.get("method") == "tasks/cancel":
            body = b"".join([chunk async for chunk in response.body_iterator])
            data = json.loads(body)
            data["result"][corrupt] = "another-task-or-context"
            return JSONResponse(data)
        return response
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    call = None
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        request = A2ARequestContext(request_id="cancel-downstream", user_id="user-a",
            session_id="session-a", caller_agent="hr_orchestrator", locale="zh-CN",
            message="查询制度", context_summary="")
        call = asyncio.create_task(OfficialA2AClient(timeout_seconds=3).invoke(
            base_url=base_url, request=request,
            spec=RemoteAgentSpec(agent_name="hr-consult-agent", agent_version="1.0.0",
                allowed_statuses=frozenset({"succeeded"}), required_fields=frozenset()),
        ))
        await asyncio.wait_for(runtime.started.wait(), 3)
        call.cancel()
        with pytest.raises(TaskCancellationError if corrupt else asyncio.CancelledError):
            await asyncio.wait_for(call, 3)
        assert runtime.stopped.is_set()
        assert len(executor._executions) == 1
        task_id = next(iter(executor._executions))
        async with httpx.AsyncClient() as http:
            response = await http.post(base_url, json={"jsonrpc": "2.0", "id": "get",
                "method": "tasks/get", "params": {"id": task_id}})
        task = response.json()["result"]
        assert task["status"]["state"] == "canceled"
        assert not task.get("artifacts")
    finally:
        if call is not None and not call.done():
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
        server.should_exit = True
        await asyncio.wait_for(serving, 5)
        sock.close()
