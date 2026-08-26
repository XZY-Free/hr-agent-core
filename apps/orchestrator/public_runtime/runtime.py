"""公共执行门面：Public Request → 校验 → 上下文归一 → 业务路径 → 公共结果。

复用现有 Orchestrator 业务路径（远程路由 + veADK Runner 本地链），
不复制 Prompt 或路由逻辑，不通过本机 HTTP 回环调用自身。
"""

import logging
from datetime import datetime

from apps.orchestrator.a2a.router import RemoteRouteResponse
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
    ):
        self.remote_router = remote_router
        self.local_runner = local_runner
        self.identity_adapter = identity_adapter or PublicIdentityAdapter()
        # 任务级本地续聊挂起键：(context_id, task_id)。仅当该键的本地链
        # 返回 input_required 时标记；终态（含失败）即清除，不做全局路由态。
        self._pending_local_continuations: set[tuple[str, str]] = set()

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
            user_id=user_id, session_id=session_id, message=message
        )
        if remote is not None:
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

    async def _invoke_remote(
        self, *, user_id: str, session_id: str, message: str
    ) -> RemoteRouteResponse | None:
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "new_message": {"parts": [{"text": message}]},
        }
        try:
            return await self.remote_router.route(payload)
        except Exception:
            logger.exception("public_runtime remote route error")
            return None

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
            answer = await self.local_runner.run(
                messages=headed, user_id=user_id, session_id=session_id
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
        answer_text = str(answer or "")
        if _looks_like_missing_info(answer_text):
            if continuation_key is not None:
                self._pending_local_continuations.add(continuation_key)
            return input_required(
                request_id=request.request_id, answer=answer_text
            )
        # 到达终态：清除挂起键，后续消息恢复正常路由。
        if continuation_key is not None:
            self._pending_local_continuations.discard(continuation_key)
        return completed(
            request_id=request.request_id, answer=answer_text
        )


# 本地链（Leave槽位收集）缺业务信息的确定性检测：模型追问必要槽位时
# 统一转成公共 input-required，SnowHarness 补充后续发同一会话。
_MISSING_INFO_KEYWORDS = (
    "假期类型",
    "哪种假",
    "什么假",
    "日期",
    "哪天",
    "开始时间",
    "时长",
    "多长时间",
    "几天",
    "事由",
    "请假原因",
)


def _looks_like_missing_info(answer: str) -> bool:
    if "？" not in answer and "?" not in answer:
        return False
    return any(keyword in answer for keyword in _MISSING_INFO_KEYWORDS)
