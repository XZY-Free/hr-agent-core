"""官方A2A AgentExecutor到独立Consult运行时的适配。"""

import logging
import time

from a2a.server.agent_execution import RequestContext
from packages.agent_runtime.a2a.cancellable_executor import CancellableExecutor
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import TaskState
from a2a.utils import new_task
from a2a.utils.errors import ServerError
from a2a.types import InvalidParamsError

from apps.consult_agent.a2a.contract import (
    ConsultA2AResult,
    RequestContractError,
    parse_consult_request,
    result_parts,
)


logger = logging.getLogger(__name__)


class ConsultAgentExecutor(CancellableExecutor):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime

    async def execute_task(self, context: RequestContext, event_queue: EventQueue) -> TaskState:
        try:
            request = parse_consult_request(context.message)
        except RequestContractError as exc:
            raise ServerError(error=InvalidParamsError(message=str(exc))) from None

        await event_queue.enqueue_event(new_task(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()
        started = time.perf_counter()
        try:
            result = await self.runtime.run(request)
        except Exception:
            result = ConsultA2AResult(
                request_id=request.request_id,
                status="failed",
                answer="咨询服务暂时不可用，请稍后重试。",
                question_category="unknown",
                error_code="internal_execution_error",
                recommend_hr=True,
            )
        await updater.add_artifact(
            result_parts(result),
            name="consult-result",
            last_chunk=True,
        )
        logger.info(
            "consult_a2a_completed request_id=%s caller=%s target=hr-consult-agent "
            "version=1.0.0 status=%s elapsed_ms=%.1f scope=%s error_code=%s",
            result.request_id,
            request.caller_agent,
            result.status,
            (time.perf_counter() - started) * 1000,
            result.knowledge_scope or "none",
            result.error_code or "none",
        )
        if result.status == "need_more_information":
            await updater.requires_input(final=True)
            return TaskState.input_required
        elif result.status == "rejected":
            await updater.reject()
            return TaskState.rejected
        elif result.status in {"temporarily_unavailable", "failed"}:
            await updater.failed()
            return TaskState.failed
        else:
            await updater.complete()
            return TaskState.completed
