"""等待实际执行退出后确认取消；供本地 A2A Provider 共用。"""

import asyncio
from dataclasses import dataclass, field

from a2a.server.agent_execution import AgentExecutor
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import InternalError, InvalidParamsError, TaskNotCancelableError, TaskState
from a2a.utils.errors import ServerError


class TaskCancellationError(Exception):
    """下游取消未获确认；不得吞掉并虚报已取消。"""


@dataclass
class _Execution:
    context_id: str
    queue: object
    work: asyncio.Task
    cancelling: bool = False
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CancellableExecutor(AgentExecutor):
    def __init__(self):
        # 与 SDK 的进程内 TaskStore 同生命周期；不宣称重启后恢复。
        self._executions: dict[str, _Execution] = {}

    async def execute(self, context, event_queue):
        previous = self._executions.get(context.task_id)
        if previous and (
            previous.context_id != context.context_id or previous.cancelling
            or not previous.work.done() or previous.work.cancelled()
            or previous.work.exception() is not None
            or previous.work.result() != TaskState.input_required
        ):
            raise ServerError(InvalidParamsError(message="任务不可重复执行或恢复"))
        execution = _Execution(
            context_id=context.context_id, queue=event_queue,
            work=asyncio.create_task(self.execute_task(context, event_queue)),
        )
        self._executions[context.task_id] = execution
        try:
            await asyncio.shield(execution.work)
        except asyncio.CancelledError:
            if execution.cancelling:
                # 保持原始事件队列开放，直到取消事件已发出。
                await execution.cancelled.wait()
            else:
                execution.work.cancel()
                await asyncio.gather(execution.work, return_exceptions=True)
                raise

    async def execute_task(self, context, event_queue) -> TaskState:
        raise NotImplementedError

    async def task_cancelled(self, context):
        pass

    async def cancel(self, context, event_queue):
        execution = self._executions.get(context.task_id)
        if execution is None or execution.context_id != context.context_id:
            raise ServerError(TaskNotCancelableError(message="无法确认任务执行状态"))
        async with execution.lock:
            if execution.cancelling:
                raise ServerError(TaskNotCancelableError(message="任务已请求取消"))
            running = not execution.work.done()
            if not running and (
                execution.work.cancelled() or execution.work.exception() is not None
                or execution.work.result() != TaskState.input_required
            ):
                raise ServerError(TaskNotCancelableError(message="任务已经结束"))
            execution.cancelling = True
            try:
                if running:
                    execution.work.cancel()
                    try:
                        await execution.work
                    except asyncio.CancelledError:
                        pass
                await self.task_cancelled(context)
                # 正在执行时发到原队列，SDK 的 cancel tap 和原 SSE 都能收到。
                # 等待输入时原队列已关闭，使用 SDK 为取消创建的独立队列。
                queue = execution.queue if running else event_queue
                await TaskUpdater(queue, context.task_id, context.context_id).cancel()
            except TaskCancellationError:
                raise ServerError(InternalError(message="无法确认下游任务已停止")) from None
            finally:
                execution.cancelled.set()
