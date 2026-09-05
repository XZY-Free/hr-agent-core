"""公共 A2A 请求处理器：任务在 SDK 修改历史前的所有者原子性守卫。

SDK 事实：DefaultRequestHandler._setup_message_execution 在 executor.execute 之前先
调用 TaskManager.update_with_message(params.message, task)，对 InMemoryTaskStore 返回的
同一 Task 对象原地改写 task.history，且 InMemoryTaskStore.get 返回的是同一对象。因此
只在 HrAssistantExecutor.execute_task 或 runtime.invoke 里做守卫已太晚，违反原子性。

本类只在“续接已有非终态任务”时，于任何改写发生前校验：当前消息的主体与任务第一条
用户消息保存的原始主体（已通过 ExecutionSubject 校验）必须一致；否则直接抛
ServerError(error=InvalidParamsError(...))（-32602），不改动任务、队列、历史或工件。
原始主体缺失/非法一律 fail closed；匿名不得接管已认证任务；subject_kind 变更视为
不同主体。首个任务消息即协议内的原始主体证据，不新建 owner 库、不重复 HR 身份权威。
"""

from __future__ import annotations

from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.types import InvalidParamsError, Message, Task, TaskState
from a2a.utils.errors import ServerError

from apps.orchestrator.public_runtime.request import ExecutionSubject

_OWNER_SAFE_MESSAGE = "当前任务服务状态与原始调用主体不一致，无法续接。"

_TERMINAL_STATES = {
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected,
}

# 无法解析出有效主体的哨兵。
_MALFORMED = object()


def _extract_owner(subject_dict) -> tuple[str, str] | None | object:
    """解析并校验公共 execution_subject；None 表匿名，其余非法返回 _MALFORMED。"""
    if subject_dict is None:
        return None
    if not isinstance(subject_dict, dict):
        return _MALFORMED
    try:
        subject = ExecutionSubject.model_validate(subject_dict)
    except Exception:
        return _MALFORMED
    return (subject.subject_kind, subject.subject_id)


def _message_owner(message: Message) -> tuple[str, str] | None | object:
    metadata = getattr(message, "metadata", None) or {}
    return _extract_owner(metadata.get("execution_subject"))


def _task_owner(task: Task) -> tuple[str, str] | None | object:
    """从任务的首条用户消息提取原始主体（协议已有证据，不是新建映射）。"""
    for item in getattr(task, "history", None) or []:
        if getattr(item, "role", None) == "user" and getattr(item, "parts", None):
            return _message_owner(item)
    return _MALFORMED


class PublicRequestHandler(DefaultRequestHandler):
    """只做公共契约层的续接所有者原子性守卫；不复制业务路由或身份映射。"""

    async def _setup_message_execution(self, params, context=None):
        message = params.message
        task = None
        if getattr(message, "task_id", None):
            task = await self.task_store.get(message.task_id, context)
        if task is not None and task.status.state not in _TERMINAL_STATES:
            self._assert_owner(task, message)
        return await super()._setup_message_execution(params, context)

    def _assert_owner(self, task: Task, message: Message) -> None:
        # context 一致性：续接消息若带 context_id 必须与任务相同，否则拒绝。
        incoming_context = getattr(message, "context_id", None)
        if incoming_context and incoming_context != task.context_id:
            raise ServerError(error=InvalidParamsError(message=_OWNER_SAFE_MESSAGE))
        original = _task_owner(task)
        incoming = _message_owner(message)
        # 原始主体缺失/非法或当前主体非法：fail closed，不允许未知主体接管。
        if original is _MALFORMED or incoming is _MALFORMED:
            raise ServerError(error=InvalidParamsError(message=_OWNER_SAFE_MESSAGE))
        # 匿名不得接管已认证任务；已认证不得接管匿名任务；主体变更一律拒绝。
        if original != incoming:
            raise ServerError(error=InvalidParamsError(message=_OWNER_SAFE_MESSAGE))
