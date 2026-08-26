"""官方A2A AgentExecutor到公共执行门面的协议适配。

只做协议转换：A2A消息 → HrAssistantRequest payload → HrAssistantResult
→ 任务终态与Artifact。不做业务路由、Tool选择、身份业务映射。
"""

import logging
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import InvalidParamsError, UnsupportedOperationError
from a2a.utils import new_task
from a2a.utils.errors import ServerError

from packages.agent_runtime.a2a.artifact import structured_result_parts


logger = logging.getLogger(__name__)

# A2A消息metadata中允许的公共合同键（execution_subject单独传递）。
_MESSAGE_METADATA_KEYS = frozenset({
    "execution_subject",
    "timezone",
    "current_datetime",
    "locale",
    "conversation_summary",
    "attachment_references",
})


class PublicContractError(Exception):
    """A2A层公共合同违规。"""


def _extract_text(message) -> str:
    if message is None or not getattr(message, "parts", None):
        raise PublicContractError("A2A消息缺少文本内容")
    texts = []
    for part in message.parts:
        text = getattr(part, "root", None)
        text = getattr(text, "text", None)
        if isinstance(text, str):
            texts.append(text)
    text = "\n".join(texts).strip()
    if not text:
        raise PublicContractError("A2A消息缺少文本内容")
    return text


def _extract_payload(context: RequestContext) -> dict:
    """A2A RequestContext → 公共请求payload；键集合严格校验。"""
    message = context.message
    metadata = dict(getattr(message, "metadata", None) or {})
    unknown = set(metadata) - _MESSAGE_METADATA_KEYS
    if unknown:
        raise PublicContractError(f"A2A消息metadata包含未知字段:{sorted(unknown)}")
    payload = {
        "request_id": context.task_id or context.context_id,
        "message": _extract_text(message),
        "context_id": context.context_id,
        "task_id": context.task_id,
        "context": {
            key: value for key, value in metadata.items()
            if key != "execution_subject"
        },
    }
    if "execution_subject" in metadata:
        payload["execution_subject"] = metadata["execution_subject"]
    return payload


class HrAssistantExecutor(AgentExecutor):
    def __init__(self, runtime):
        self.runtime = runtime

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            payload = _extract_payload(context)
        except PublicContractError as exc:
            raise ServerError(error=InvalidParamsError(message=str(exc))) from None

        # Resume语义：客户端在input-required后引用原taskId续发消息时，
        # context.current_task存在，继续同一任务而不是创建新任务。
        task = context.current_task
        if task is None:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        payload["request_id"] = task.id
        await updater.start_work()
        started = time.perf_counter()
        result = await self.runtime.invoke(payload)
        await updater.add_artifact(
            structured_result_parts(result.answer, result.to_payload()),
            name="hr-assistant-result",
            last_chunk=True,
        )
        logger.info(
            "hr_assistant_a2a_completed request_id=%s status=%s elapsed_ms=%.1f "
            "error_code=%s",
            result.request_id,
            result.status,
            (time.perf_counter() - started) * 1000,
            result.error_code or "none",
        )
        if result.status == "input_required":
            await updater.requires_input(final=True)
        elif result.status == "rejected":
            await updater.reject()
        elif result.status == "failed":
            await updater.failed()
        else:
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 公共合同 cancel=false：底层veADK/Tool无法真实中断，禁止把Task
        # 标成cancelled但业务仍在运行的伪取消。tasks/cancel 一律返回
        # a2a-sdk官方unsupported-operation错误。
        raise ServerError(error=UnsupportedOperationError())
