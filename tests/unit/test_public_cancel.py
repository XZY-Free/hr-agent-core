"""真实 asyncio 工作任务与官方事件队列的取消行为。"""

import asyncio

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import Message, MessageSendParams, Part, Role, Task, TaskState, TaskStatus, TextPart

from apps.orchestrator.public_a2a.executor import HrAssistantExecutor
from apps.orchestrator.public_runtime.result import input_required
from a2a.utils.errors import ServerError
from packages.agent_runtime.a2a.cancellable_executor import TaskCancellationError


def context(task_id="task-a", state=TaskState.working):
    task = Task(id=task_id, context_id="ctx-a", status=TaskStatus(state=state))
    return RequestContext(
        MessageSendParams(message=Message(
            message_id="message-a", role=Role.user,
            parts=[Part(root=TextPart(text="我想请假"))],
        )), task_id=task_id, context_id="ctx-a", task=task,
    )


class RuntimeWork:
    def __init__(self, waiting=False):
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.waiting = waiting
        self.cleared = []

    async def invoke(self, payload):
        self.started.set()
        try:
            if not self.waiting:
                await asyncio.Event().wait()
            return input_required(request_id=payload["request_id"], answer="请补充日期")
        finally:
            self.stopped.set()

    async def cancel_pending(self, context_id, task_id):
        self.cleared.append((context_id, task_id))


@pytest.mark.asyncio
async def test_cancel_waits_for_running_work_to_exit_and_clears_continuation():
    runtime = RuntimeWork()
    executor = HrAssistantExecutor(runtime)
    queue = EventQueue()
    work = asyncio.create_task(executor.execute(context(), queue))
    await asyncio.wait_for(runtime.started.wait(), 1)
    cancel_queue = queue.tap()
    try:
        await executor.cancel(context(), cancel_queue)
        assert runtime.stopped.is_set()
        assert runtime.cleared == [("ctx-a", "task-a")]
        event = await asyncio.wait_for(cancel_queue.dequeue_event(), 1)
        assert event.status.state == TaskState.canceled
        assert event.final is True
        await asyncio.wait_for(work, 1)
    finally:
        if not work.done():
            work.cancel()
        await asyncio.gather(work, return_exceptions=True)


@pytest.mark.asyncio
async def test_waiting_task_cancel_and_other_task_isolation():
    runtime = RuntimeWork(waiting=True)
    executor = HrAssistantExecutor(runtime)
    await executor.execute(context(), EventQueue())
    await executor.execute(context("task-b"), EventQueue())
    queue = EventQueue()
    await executor.cancel(context(state=TaskState.input_required), queue)
    event = await asyncio.wait_for(queue.dequeue_event(), 1)
    assert event.status.state == TaskState.canceled
    assert runtime.cleared == [("ctx-a", "task-a")]
    other = EventQueue()
    await executor.cancel(context("task-b", TaskState.input_required), other)
    assert (await other.dequeue_event()).task_id == "task-b"
    with pytest.raises(ServerError, match="任务不可重复执行或恢复"):
        await executor.execute(context(), EventQueue())


@pytest.mark.asyncio
async def test_unconfirmed_downstream_stop_never_emits_cancelled():
    class FailedStop(RuntimeWork):
        async def invoke(self, payload):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise TaskCancellationError()

    runtime = FailedStop()
    executor = HrAssistantExecutor(runtime)
    queue = EventQueue()
    work = asyncio.create_task(executor.execute(context(), queue))
    await runtime.started.wait()
    tap = queue.tap()
    with pytest.raises(ServerError, match="无法确认下游任务已停止"):
        await executor.cancel(context(), tap)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(tap.dequeue_event(), 0.02)
    assert runtime.cleared == []
    await asyncio.gather(work, return_exceptions=True)
