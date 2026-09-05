"""公共执行门面：Public Request → 校验 → 上下文归一 → 业务路径 → 公共结果。

复用现有 Orchestrator 业务路径（远程路由 + veADK Runner 本地链），
不复制 Prompt 或路由逻辑，不通过本机 HTTP 回环调用自身。
"""

import dataclasses
import hashlib
import logging
from datetime import datetime

from apps.orchestrator.a2a.router import (
    CONSULT_SPEC,
    EMPLOYEE_SPEC,
    LocalLeaveDispatch,
    RemoteRouteResponse,
)
from apps.orchestrator.public_runtime.attachments import (
    AccessMode,
    AttachmentResolutionError,
)
from packages.agent_runtime.a2a.cancellable_executor import TaskCancellationError
from packages.hr_domain.documents.context import (
    DocumentContextError,
    MAX_TOTAL_CONTENT,
    encode_document_context,
)
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

# WP-02：ADK 会话隔离。同 context 不同 task 必须用不同 session key，否则共享 draft 与
# LLM 历史会串。公共 context/task 保持原值（HR context 仍用原始 context_id），只在此
# 派生 local runner 的 task-scoped session key。
def _adk_session_key(context_id: str, task_id: str | None) -> str:
    """确定性编码 (context, task)；用 SHA-256 而非简单拼接，避免分隔符碰撞。"""
    composite = repr((context_id, task_id))
    digest = hashlib.sha256(composite.encode("utf-8")).hexdigest()
    return f"task-session-{digest}"


# Leave 草稿需要用户补充/确认/更正的状态：公共层一律 input_required。
_LEAVE_INPUT_REQUIRED_STATUSES = frozenset({
    "collecting",
    "ready_for_confirmation",
    "validation_failed",
})

# Leave 草稿确认成功/终态：公共层 completed（answer 用工具确定性文案，不走 LLM）。
_LEAVE_TERMINAL_CONFIRMED_STATUSES = frozenset({"confirmed", "terminal"})

# 语义低置信度/歧义产生的本地澄清：target 是固定三值契约的 "local"。它由
# OrchestratorRemoteRouter 直接返回的固定澄清，不属于远程续接 owner，不得登记到
# _pending_remote_users。
_LOCAL_CLARIFICATION_TARGET = "local"

# 本地续聊 owner 枚举：同 (context_id, task_id) 挂起时按 owner 选 leave_runner / root
# local_runner。未知 owner 一律 fail closed；不把所有本地 pending 硬编码成 Leave。
_LOCAL_OWNER_LEAVE = "local_leave"
_LOCAL_OWNER_ROOT = "root"


def _map_document_error(exc: DocumentContextError) -> AttachmentResolutionError:
    """把文档上下文校验错误映射为稳定附件错误码；不回显任何输入内容。"""
    if exc.code == "document_context_sensitive":
        return AttachmentResolutionError("attachment_sensitive", "附件包含敏感内容。")
    if exc.code in ("document_context_too_large", "document_context_too_many"):
        return AttachmentResolutionError("attachment_too_large", "附件内容超出上限。")
    return AttachmentResolutionError("attachment_invalid", "附件解析结果无效。")


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


def _canonical_route_target(target: str) -> str:
    """把 RemoteRouteResponse.target 收束为固定三值契约（local/consult/employee_data）。

    只输出三值之一，绝不把内部 agent 名（hr-consult-agent / hr-employee-data-agent）
    写入公共 data；未知 target 必须 fail closed（抛错而非默认为 employee_data），
    防止生成伪造路由证据。来源是远程路由的固定 target，不由模型或下游自由提供。
    """
    if target == _LOCAL_CLARIFICATION_TARGET:
        return "local"
    if target == CONSULT_SPEC.agent_name:
        return "consult"
    if target == EMPLOYEE_SPEC.agent_name:
        return "employee_data"
    raise ValueError(f"未知远程路由 target: {target!r}")


def _map_remote(
    response: RemoteRouteResponse, *, request: HrAssistantRequest
) -> HrAssistantResult:
    try:
        canonical = _canonical_route_target(response.target)
    except ValueError:
        # 未知 target：fail closed 为稳定 failed。不写已知三值/route_target 伪证据、
        # 不回显未知原值或内部异常消息，仅给固定安全文案与契约错误码，杜绝穿出到 executor。
        return failed(
            request_id=request.request_id,
            answer="服务暂无法处理该请求，请稍后重试。",
            error_code="route_contract_error",
            retryable=False,
        )
    if response.status == "need_more_information":
        return input_required(
            request_id=request.request_id,
            answer=response.answer,
            data={"route_target": canonical},
        )
    # 复用现有 result_type 判定（consult → consultation / employee_data → employee_data）；
    # 未知 target 已在 _canonical_route_target 里 fail closed，不会落到默认 employee_data。
    result_type = "consultation" if canonical == "consult" else "employee_data"
    if response.status == "succeeded":
        return completed(
            request_id=request.request_id,
            answer=response.answer,
            result_type=result_type,
            data={"route_target": canonical},
        )
    if response.status == "not_found":
        return HrAssistantResult(
            request_id=request.request_id,
            status="completed",
            answer=response.answer,
            result_type=result_type,
            error_code="not_found",
            data={"route_target": canonical},
        )
    if response.status == "rejected":
        return rejected(
            request_id=request.request_id,
            answer=response.answer,
            error_code=response.error_code or "rejected",
            data={"route_target": canonical},
        )
    return failed(
        request_id=request.request_id,
        answer=response.answer,
        error_code=response.error_code or "failed",
        data={"route_target": canonical},
    )


class HrAssistantRuntime:
    """唯一公共执行门面。"""

    def __init__(
        self,
        *,
        remote_router,
        local_runner,
        leave_runner=None,
        identity_adapter: PublicIdentityAdapter | None = None,
        hr_context_builder=None,
        attachment_resolver=None,
    ):
        self.remote_router = remote_router
        self.local_runner = local_runner
        self.leave_runner = leave_runner
        self.identity_adapter = identity_adapter or PublicIdentityAdapter()
        # 装配好的 request-bound HR execution context 构建器。为 None 时
        # 本地链不注入 HR 执行上下文（此时 gaia 业务工具 fail closed 为
        # identity_unverified）。由 public_a2a.server 装配共享 resolver/provider。
        self._hr_context_builder = hr_context_builder
        self._attachment_resolver = attachment_resolver
        # 任务级本地续聊挂起 owner：(context_id, task_id) -> owner（local_leave / root）。
        # 仅当该键的本地链返回 input_required 时标记 owner；终态（含失败/异常/cancel）即
        # 清除，不同 task 不继承；同 key 续接按 owner 选 leave_runner / root local_runner，
        # 绝不把所有本地 pending 硬编码成 Leave。
        self._pending_local_continuations: dict[tuple[str, str], str] = {}
        self._pending_remote_users: dict[tuple[str, str], str] = {}

    async def cancel_pending(self, context_id: str, task_id: str) -> None:
        key = (context_id, task_id)
        user_id = self._pending_remote_users.get(key)
        if user_id is not None:
            await self.remote_router.cancel_pending(user_id=user_id,
                session_id=context_id, task_id=task_id)
            self._pending_remote_users.pop(key, None)
        self._pending_local_continuations.pop(key, None)

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
        # 按已登记 owner 选择 leave_runner / root local_runner（不硬编码为 Leave）。
        continuation_key = self._continuation_key(request)
        pending_owner = (
            self._pending_local_continuations.get(continuation_key)
            if continuation_key is not None else None
        )
        if pending_owner is not None:
            return await self._invoke_local(
                request=request,
                user_id=user_id,
                session_id=session_id,
                continuation_key=continuation_key,
                owner=pending_owner,
            )

        remote = await self._invoke_remote(
            user_id=user_id, session_id=session_id, message=message, task_id=request.task_id,
            attachment_context_summary=attachment_doc_context,
        )
        if isinstance(remote, LocalLeaveDispatch):
            # 确定性本地 Leave 派发：semantic decision=leave_transaction，不走 Root，
            # 直接跑 leave_runner 并登记 local_leave owner；不是公共远程状态。
            return await self._invoke_local(
                request=request,
                user_id=user_id,
                session_id=session_id,
                continuation_key=continuation_key,
                owner=_LOCAL_OWNER_LEAVE,
            )
        if remote is not None:
            # 本地澄清不属于远程续接 owner，不登记远程 pending；其余按原逻辑。
            if continuation_key is not None and remote.target != _LOCAL_CLARIFICATION_TARGET:
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
            owner=_LOCAL_OWNER_ROOT,
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
        - 仅上传附件未提问 → input_required 澄清（先于任何解析/路由/模型）；
        - 无 resolver / 解析失败 → 明确错误（不静默忽略、不假装已读取）；
        - 解析成功 → 构造 DocumentContext 摘要（encode_document_context）供 Consult 读取。
        """
        references = request.context.attachment_references
        if not references:
            return None, None
        if not request.normalized_message():
            return self._attachment_input_required(request), None
        if self._attachment_resolver is None:
            return self._attachment_error(
                request, "attachment_not_resolvable",
                "当前附件引用暂时无法读取，请提供可访问的文档链接或使用已支持的附件来源。",
            ), None
        try:
            resolved = self._attachment_resolver.resolve_all(references)
        except AttachmentResolutionError as exc:
            return self._attachment_error(request, exc.error_code, exc.message), None
        try:
            summary = self._attachment_summary(resolved)
        except AttachmentResolutionError as exc:
            return self._attachment_error(request, exc.error_code, exc.message), None
        return None, summary

    @staticmethod
    def _attachment_summary(resolved) -> str:
        """把全部已解析附件按输入顺序编码为 DocumentContext 摘要。

        - TEXT 附件：canonical_reference + 已净化 content（可选 display/media），不伪造 URL；
        - URL 附件：canonical_reference + URL（无任何占位 content）；
        - 保持输入顺序；不静默截断；聚合/校验问题映射为稳定的
          AttachmentResolutionError（attachment_too_large / attachment_sensitive /
          attachment_invalid），由 _resolve_attachments 收敛为结构化失败。
        绝不写出「附件待解析」这类占位文本。
        """
        documents: list[dict] = []
        total_content = 0
        for attachment in resolved:
            doc: dict = {"canonical_reference": attachment.canonical_reference}
            if attachment.display_name:
                doc["display_name"] = attachment.display_name
            if attachment.media_type:
                doc["media_type"] = attachment.media_type
            if attachment.access_mode is AccessMode.URL:
                if not attachment.url:
                    raise AttachmentResolutionError(
                        "attachment_invalid", "附件引用缺少可访问地址。"
                    )
                doc["url"] = attachment.url
            else:
                if not attachment.text:
                    raise AttachmentResolutionError(
                        "attachment_invalid", "附件引用缺少内容。"
                    )
                total_content += len(attachment.text)
                doc["content"] = attachment.text
            documents.append(doc)
        if total_content > MAX_TOTAL_CONTENT:
            raise AttachmentResolutionError(
                "attachment_too_large", "附件内容总量超出上限。"
            )
        try:
            return encode_document_context({"documents": documents})
        except DocumentContextError as exc:
            raise _map_document_error(exc) from None

    @staticmethod
    def _attachment_input_required(request) -> HrAssistantResult:
        return input_required(
            request_id=request.request_id,
            answer="您上传了附件，请说明想了解的具体问题。",
        )

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
    ) -> RemoteRouteResponse | LocalLeaveDispatch | None:
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
        self, *, runner, user_id: str, session_id: str, headed: str, request: HrAssistantRequest
    ):
        """在 request-scoped HR execution context 下运行本地链（root 或 leave runner）。

        有装配好的 builder 时绑定共享身份/Gaia 上下文；无 builder 时直接运行
        （此时 gaia 业务工具 fail closed 为 identity_unverified）。同一请求内
        的工具调用共享一次绑定，返回后即清理，不跨请求继承。
        """
        if self._hr_context_builder is None:
            return await runner.run(
                messages=headed, user_id=user_id, session_id=session_id
            )
        ctx = self._hr_context_builder(
            internal_user_id=user_id,
            request_id=request.request_id,
            context_id=request.context_id,
        )
        # 绑定本轮原始用户文本（非系统上下文/历史摘要），供确认判定与来源追溯；
        # 用 dataclasses.replace 以免扩大 builder 签名。
        ctx = dataclasses.replace(ctx, current_user_message=request.normalized_message())
        with bind_hr_execution_context(ctx):
            return await runner.run(
                messages=headed, user_id=user_id, session_id=session_id
            )

    def _runner_for_local(self, owner: str):
        """按 owner 选 runner；未知 owner / 缺 leave_runner 一律返回 None（fail closed）。"""
        if owner == _LOCAL_OWNER_LEAVE:
            return self.leave_runner
        if owner == _LOCAL_OWNER_ROOT:
            return self.local_runner
        return None

    async def _invoke_local(
        self,
        *,
        request: HrAssistantRequest,
        user_id: str,
        session_id: str,
        continuation_key: tuple[str, str] | None = None,
        owner: str,
    ) -> HrAssistantResult:
        # 未知 owner 或 leave_runner 缺失：稳定 failed，绝不回退 Root，也不登记 owner。
        runner = self._runner_for_local(owner)
        if runner is None:
            if continuation_key is not None:
                self._pending_local_continuations.pop(continuation_key, None)
            return failed(
                request_id=request.request_id,
                answer="智能体暂时无法处理，请稍后重试。",
                error_code="failed",
            )
        # 本地链消息带执行上下文头与独立历史摘要区块；用户正文始终在后。
        headed = (
            _context_header(request.context)
            + _summary_block(request.context)
            + request.normalized_message()
        )
        adk_session = _adk_session_key(request.context_id, request.task_id)
        try:
            turn = await self._run_local_bound(
                runner=runner,
                user_id=user_id,
                session_id=adk_session,
                headed=headed,
                request=request,
            )
        except Exception:
            logger.exception(
                "public_runtime local run error request_id=%s", request.request_id
            )
            # 本地续聊失败同样是终态：清除挂起键，下次走正常路由。
            if continuation_key is not None:
                self._pending_local_continuations.pop(continuation_key, None)
            return failed(
                request_id=request.request_id,
                answer="智能体暂时无法处理，请稍后重试。",
                error_code="failed",
            )
        if turn.terminal_error_code is not None:
            # 权威身份校验失败：终态 rejected + identity_unverified，固定安全话术，
            # 不回显 raw provider error；清除挂起键，使后续消息恢复正常路由。
            if continuation_key is not None:
                self._pending_local_continuations.pop(continuation_key, None)
            return rejected(
                request_id=request.request_id,
                answer="当前身份无法完成本人数据查询。",
                error_code=turn.terminal_error_code,
            )
        if turn.leave_draft is not None and turn.leave_draft.get("status") in _LEAVE_INPUT_REQUIRED_STATUSES:
            # Leave 草稿结构化状态：collecting / ready_for_confirmation /
            # validation_failed 均映射公共 input_required，并携带 data.draft /
            # missing_fields / validation_error。状态由领域 MissingFields 裁决，
            # 不由自然语言或 request_user_input 决定。
            draft_status = turn.leave_draft.get("status")
            if continuation_key is not None:
                self._pending_local_continuations[continuation_key] = owner
            # answer 由领域从 draft/missing/validation_error 确定性生成，不用 LLM 文本，
            # 避免模型随口改写权威天数（如 data=3 天、LLM 却答 1 天）。
            answer = (
                turn.leave_draft.get("answer")
                or ("请补充请假信息，以便完成申请。" if draft_status == "collecting"
                    else "请核对您的请假申请。")
            )
            return input_required(
                request_id=request.request_id,
                answer=answer,
                data={
                    "route_target": _LOCAL_CLARIFICATION_TARGET,
                    "draft": turn.leave_draft.get("draft"),
                    "missing_fields": turn.leave_draft.get("missing_fields", []),
                    "validation_error": turn.leave_draft.get("validation_error"),
                },
            )
        if turn.leave_draft is not None and turn.leave_draft.get("status") in _LEAVE_TERMINAL_CONFIRMED_STATUSES:
            # 确认/终态：公共 completed 且 answer 由工具确定性文案，绝不用 LLM turn.answer
            # 伪装业务结果（避免模型随口改权威数字）；data.draft 保留，并带最终提交表单内容。
            # 终态到达即清续接挂起键。
            if continuation_key is not None:
                self._pending_local_continuations.pop(continuation_key, None)
            return completed(
                request_id=request.request_id,
                answer=turn.leave_draft.get("answer") or "已确认您的请假申请。",
                data={
                    "route_target": _LOCAL_CLARIFICATION_TARGET,
                    "draft": turn.leave_draft.get("draft"),
                    "missing_fields": turn.leave_draft.get("missing_fields", []),
                    "validation_error": turn.leave_draft.get("validation_error"),
                    "submission": turn.leave_draft.get("submission"),
                },
            )
        if turn.input_question is not None:
            if continuation_key is not None:
                self._pending_local_continuations[continuation_key] = owner
            return input_required(
                request_id=request.request_id, answer=turn.input_question
            )
        # 到达终态：清除挂起键，后续消息恢复正常路由。
        if continuation_key is not None:
            self._pending_local_continuations.pop(continuation_key, None)
        return completed(
            request_id=request.request_id, answer=turn.answer
        )
