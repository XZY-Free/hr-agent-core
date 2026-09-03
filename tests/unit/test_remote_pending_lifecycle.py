"""公开任务暂停后，恢复和取消必须操作它自己的下游任务。"""

import asyncio
import socket

import httpx
import pytest
import uvicorn
from a2a.server.agent_execution import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import Message, MessageSendParams, Task, TaskState, TaskStatus

from apps.consult_agent.a2a.card import build_agent_card
from apps.consult_agent.a2a.contract import ConsultA2AResult
from apps.consult_agent.a2a.executor import ConsultAgentExecutor
from apps.orchestrator.a2a.router import OrchestratorRemoteRouter
from apps.orchestrator.public_a2a.executor import HrAssistantExecutor
from apps.orchestrator.public_runtime.runtime import HrAssistantRuntime
from packages.agent_runtime.a2a.server import build_jsonrpc_app
from packages.agent_runtime.user_input import TurnOutput


@pytest.mark.asyncio
async def test_waiting_remote_task_resume_cancel_and_task_isolation():
    class ConsultWork:
        async def run(self, request):
            return ConsultA2AResult(request_id=request.request_id,
                status="need_more_information", answer="请补充业务信息", question_category="policy")

    class LocalWork:
        async def run(self, **kwargs):
            return TurnOutput(answer="本地回答")

    downstream = ConsultAgentExecutor(ConsultWork())
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = build_jsonrpc_app(agent_card=build_agent_card(url), agent_executor=downstream,
        title="pending-test", health={})
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    router = OrchestratorRemoteRouter(consult_url=url)
    public = HrAssistantExecutor(HrAssistantRuntime(remote_router=router, local_runner=LocalWork()))

    def context(task_id, text="育儿假政策"):
        message = Message(messageId=f"msg-{task_id}", role="user",
            parts=[{"kind": "text", "text": text}])
        task = Task(id=task_id, contextId="ctx-a", status=TaskStatus(state=TaskState.input_required))
        return RequestContext(MessageSendParams(message=message), task_id=task_id,
            context_id="ctx-a", task=task)

    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        await public.execute(context("task-a"), EventQueue())
        task_a = next(iter(downstream._executions))
        await public.execute(context("task-b"), EventQueue())
        task_b = next(key for key in downstream._executions if key != task_a)
        await public.execute(context("task-a", "四川"), EventQueue())
        assert len(downstream._executions) == 2, "补充信息不能遗留旧任务并创建新下游任务"
        await public.cancel(context("task-a"), EventQueue())
        async with httpx.AsyncClient() as http:
            async def state(task_id):
                response = await http.post(url, json={"jsonrpc": "2.0", "id": "get",
                    "method": "tasks/get", "params": {"id": task_id}})
                return response.json()["result"]["status"]["state"]
            assert await state(task_a) == "canceled"
            assert await state(task_b) == "input-required"
        # 新任务不能继承另一个暂停任务的路由，即使同一个context。
        await public.execute(context("task-c", "四川"), EventQueue())
        assert len(downstream._executions) == 2
        await public.cancel(context("task-b"), EventQueue())
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 5)
        sock.close()
