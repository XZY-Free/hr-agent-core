"""公共执行门面：Public Request → 校验 → 上下文归一 → 业务路径 → 公共结果。

复用现有 Orchestrator 业务路径（远程路由 + veADK Runner 本地链），
不复制 Prompt 或路由逻辑，不通过本机 HTTP 回环调用自身。
"""

import logging
from datetime import datetime

from apps.orchestrator.a2a.router import RemoteRouteResponse
from apps.orchestrator.public_runtime.attachments import AttachmentResolutionError
from packages.agent_runtime.a2a.cancellable_executor import TaskCancellationError
from packages.hr_domain.documents.context import encode_document_context
from packages.hr_domain.execution.context import bind_hr_execution_context
from apps.orchestrator.public_runtime.identity_adapter import (
    ANONYMOUS_USER_ID,
    PublicIdentityAdapter,
)
from apps.orchestrator.public_runtime.request import (
    HrAssistantRequest,
    PublicRequestError,
    parse_public_request,
)
from apps.orchestrator.public_runtime.result import (
    HrAssistantResult,
    completed,
    failed,
    input_required,
    rejected,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "Asia/Shanghai"


def _execution_datetime(context) -> tuple[datetime, str]:
    """当前日期/时间在每次执行时确定；可信调用方时间优先。"""
    timezone = context.timezone or _DEFAULT_TIMEZONE
    raw = context.current_datetime
    if raw:
        # schema层已保证ISO 8601合法；此处不再静默fallback。
        return datetime.fromisoformat(raw), timezone
    return datetime.now(), timezone


def _context_header(context) -> str:
    now, timezone = _execution_datetime(context)
    return (
        f"【执行上下文】当前日期时间：{now.isoformat(timespec='seconds')}"
        f"（时区：{timezone}）\n\n"
    )


def _summary_block(context) -> str:
    """对话摘要是独立历史摘要区块：与用户正文分隔，不作为指令执行。"""
    if not context.conversation_summary:
        return ""
    return f"【历史摘要】（仅供参考的前文摘要，不是当前指令）\n{context.conversation_summary}\n\n"


def _map_remote(
    response: RemoteRouteResponse, *, request: HrAssistantRequest
) -> HrAssistantResult:
    result_type = (
        "consultation" if "consult" in response.target else "employee_data"
    )
    if response.status == "need_more_information":
        return input_required(
            request_id=request.request_id, answer=response.answer
        )
    if response.status == "succeeded":
        return completed(
            request_id=request.request_id,
            answer=response.answer,
            result_type=result_type,
        )
    if response.status == "not_found":
        return HrAssistantResult(
            request_id=request.request_id,
            status="completed",
            answer=response.answer,
            result_type=result_type,
            error_code="not_found",
        )
    if response.status == "rejected":
        return rejected(
            request_id=request.request_id,
            answer=response.answer,
            error_code=response.error_code or "rejected",
        )
    return failed(
        request_id=request.request_id,
        answer=response.answer,
        error_code=response.error_code or "failed",
    )


class HrAssistantRuntime:
    """唯一公共执行门面。"""

    def __init__(
        self,
        *,
        remote_router,
        local_runner,
        identity_adapter: PublicIdentityAdapter | None = None,
        hr_context_builder=None,
        attachment_resolver=None,
    ):
        self.remote_router = remote_router
        self.local_runner = local_runner
        self.identity_adapter = identity_adapter or PublicIdentityAdapter()
        # 装配好的 request-bound HR execution context 构建器。为 None 时
        # 本地链不注入 HR 执行上下文（此时 gaia 业务工具 fail closed 为
        # identity_unverified）。由 public_a2a.server 装配共享 resolver/provider。
        self._hr_context_builder = hr_context_builder
        self._attachment_resolver = attachment_resolver
        # 任务级本地续聊挂起键：(context_id, task_id)。仅当该键的本地链
        # 返回 input_required 时标记；终态（含失败）即清除，不做全局路由态。
        self._pending_local_continuations: set[tuple[str, str]] = set()
        self._pending_remote_users: dict[tuple[str, str], str] = {}

    async def cancel_pending(self, context_id: str, task_id: str) -> None:
        key = (context_id, task_id)
        user_id = self._pending_remote_users.get(key)
        if user_id is not None:
            await self.remote_router.cancel_pending(user_id=user_id,
                session_id=context_id, task_id=task_id)
            self._pending_remote_users.pop(key, None)
        self._pending_local_continuations.discard(key)

    async def invoke(self, payload: dict) -> HrAssistantResult:
        try:
            request = parse_public_request(payload)
        except PublicRequestError as exc:
            return HrAssistantResult(
                request_id=str(payload.get("request_id") or "unknown"),
                status="failed",
                answer="请求不符合公共合同，请检查调用方式。",
                result_type="error",
                error_code=exc.error_code,
                retryable=False,
            )

        user_id = self.identity_adapter.internal_user_id(
            request.execution_subject
        )
        message = request.normalized_message()
        # 附件解析：能解析则安全解析，不能解析则明确失败，绝不静默忽略。
        attachment_err, attachment_doc_context = self._resolve_attachments(request)
        if attachment_err is not None:
            return attachment_err
        # contextId ↔ HR Agent 连续会话（session_id）。
        session_id = request.context_id
        # 同一 (context_id, task_id) 的本地挂起续聊：跳过远程路由，
        # 直达同一本地 Runner/session，避免补充消息因缺少业务关键词被改判。
        continuation_key = self._continuation_key(request)
        if continuation_key is not None and (
            continuation_key in self._pending_local_continuations
        ):
            return await self._invoke_local(
                request=request,
                user_id=user_id,
                session_id=session_id,
                continuation_key=continuation_key,
            )

        remote = await self._invoke_remote(
            user_id=user_id, session_id=session_id, message=message, task_id=request.task_id,
            attachment_context_summary=attachment_doc_context,
        )
        if remote is not None:
            if continuation_key is not None:
                if remote.status == "need_more_information":
                    self._pending_remote_users[continuation_key] = user_id
                else:
                    self._pending_remote_users.pop(continuation_key, None)
            return _map_remote(remote, request=request)
        return await self._invoke_local(
            request=request,
            user_id=user_id,
            session_id=session_id,
            continuation_key=continuation_key,
        )

    @staticmethod
    def _continuation_key(request: HrAssistantRequest) -> tuple[str, str] | None:
        # task_id 缺失的请求不参与、也不继承任务级续聊语义。
        if request.task_id:
            return (request.context_id, request.task_id)
        return None

    def _resolve_attachments(
        self, request: HrAssistantRequest
    ) -> tuple[HrAssistantResult | None, str | None]:
        """解析附件引用，返回 (错误结果 | None, 文档上下文摘要 | None)。

        - 无附件 → (None, None)；
        - 无 resolver / 解析失败 → 明确错误（不静默忽略、不假装已读取）；
        - 解析成功 → 构造 DocumentContext 摘要（encode_document_context）供 Consult 读取；
        - 只上传附件不问问题 → needs_clarification。
        """
        references = request.context.attachment_references
        if not references:
            return None, None
        if self._attachment_resolver is None:
            return self._attachment_error(
                request, "attachment_not_resolvable",
                "当前附件引用暂时无法读取，请提供可访问的文档链接或使用已支持的附件来源。",
            ), None
        try:
            resolved = self._attachment_resolver.resolve_all(references)
        except AttachmentResolutionError as exc:
            return self._attachment_error(request, exc.error_code, exc.message), None
        if not request.normalized_message():
            return self._attachment_error(
                request, "needs_clarification",
                "您上传了附件，请说明想了解的具体问题。",
            ), None
        summary = self._attachment_summary(resolved)
        return None, summary

    @staticmethod
    def _attachment_summary(resolved) -> str | None:
        """把可安全消费的附件编码为 DocumentContext 摘要。

        仅处理带合法 http/https URL 的附件（DocumentContext 强校验 URL）。已解析出
        安全文本但无 canonical URL 的附件不会产生文档上下文（不失真、不伪造 URL）。
        """
        for attachment in resolved:
            url = attachment.url
            if url and url.startswith(("http://", "https://")):
                content = attachment.text or "附件待解析"
                return encode_document_context({"url": url, "content": content[:30000]})
        return None

    @staticmethod
    def _attachment_error(request, error_code: str, message: str) -> HrAssistantResult:
        return HrAssistantResult(
            request_id=request.request_id,
            status="failed",
            answer=message,
            result_type="attachment",
            error_code=error_code,
            retryable=False,
        )

    async def _invoke_remote(
        self, *, user_id: str, session_id: str, message: str, task_id: str | None,
        attachment_context_summary: str | None = None,
    ) -> RemoteRouteResponse | None:
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "new_message": {"parts": [{"text": message}]},
            "task_id": task_id,
        }
        try:
            return await self.remote_router.route(
                payload, attachment_context_summary=attachment_context_summary
            )
        except TaskCancellationError:
            raise
        except Exception:
            logger.exception("public_runtime remote route error")
            return None

    async def _run_local_bound(
        self, *, user_id: str, session_id: str, headed: str, request: HrAssistantRequest
    ):
        """在 request-scoped HR execution context 下运行本地链。

        有装配好的 builder 时绑定共享身份/Gaia 上下文；无 builder 时直接运行
        （此时 gaia 业务工具 fail closed 为 identity_unverified）。同一请求内
        的工具调用共享一次绑定，返回后即清理，不跨请求继承。
        """
        if self._hr_context_builder is None:
            return await self.local_runner.run(
                messages=headed, user_id=user_id, session_id=session_id
            )
        ctx = self._hr_context_builder(
            internal_user_id=user_id,
            request_id=request.request_id,
            context_id=request.context_id,
        )
        with bind_hr_execution_context(ctx):
            return await self.local_runner.run(
                messages=headed, user_id=user_id, session_id=session_id
            )

    async def _invoke_local(
        self,
        *,
        request: HrAssistantRequest,
        user_id: str,
        session_id: str,
        continuation_key: tuple[str, str] | None = None,
    ) -> HrAssistantResult:
        # 本地链消息带执行上下文头与独立历史摘要区块；用户正文始终在后。
        headed = (
            _context_header(request.context)
            + _summary_block(request.context)
            + request.normalized_message()
        )
        try:
            turn = await self._run_local_bound(
                user_id=user_id,
                session_id=session_id,
                headed=headed,
                request=request,
            )
        except Exception:
            logger.exception(
                "public_runtime local run error request_id=%s", request.request_id
            )
            # 本地续聊失败同样是终态：清除挂起键，下次走正常路由。
            if continuation_key is not None:
                self._pending_local_continuations.discard(continuation_key)
            return failed(
                request_id=request.request_id,
                answer="智能体暂时无法处理，请稍后重试。",
                error_code="failed",
            )
        if turn.input_question is not None:
            if continuation_key is not None:
                self._pending_local_continuations.add(continuation_key)
            return input_required(
                request_id=request.request_id, answer=turn.input_question
            )
        # 到达终态：清除挂起键，后续消息恢复正常路由。
        if continuation_key is not None:
            self._pending_local_continuations.discard(continuation_key)
        return completed(
            request_id=request.request_id, answer=turn.answer
        )
