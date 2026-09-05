"""顶层公共A2A服务：AgentCard、JSON-RPC端点、健康检查与访问认证。

公共合同是运营方导入SnowHarness的显式请求工件（生成器产物），
远程运行时不暴露合同发现端点。

端点与认证配置的唯一Authority是 public_a2a.settings：本模块只消费
显式传入的 settings，不自行读取环境变量。
"""

import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from packages.agent_runtime.a2a.server import build_jsonrpc_app

from apps.orchestrator.public_a2a.card import build_agent_card
from apps.orchestrator.public_a2a.executor import HrAssistantExecutor
from apps.orchestrator.public_a2a.request_handler import PublicRequestHandler
from apps.orchestrator.public_a2a.settings import (
    ENV_BEARER_TOKEN,
    PublicA2ASettings,
)

logger = logging.getLogger(__name__)

# 无需认证（协议证据端点）：健康检查与AgentCard发现。
_UNAUTHENTICATED_PATHS = frozenset({
    "/health",
    "/.well-known/agent-card.json",
})


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Runtime Access Credential：JSON-RPC端点要求Bearer认证。

    只证明调用权，与execution_subject（代表谁）无关。
    token校验constant-time；token不进入日志或响应体。
    """

    def __init__(self, app, token: str):
        super().__init__(app)
        self._expected = token.encode("utf-8")

    async def dispatch(self, request, call_next):
        if request.url.path in _UNAUTHENTICATED_PATHS:
            return await call_next(request)
        authorization = request.headers.get("authorization") or ""
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credential.strip():
            return JSONResponse(
                {"detail": "缺少Bearer认证凭据"}, status_code=401
            )
        supplied = credential.strip().encode("utf-8")
        if not hmac.compare_digest(supplied, self._expected):
            logger.warning(
                "public_a2a auth rejected: invalid bearer credential "
                "(path=%s)", request.url.path,
            )
            return JSONResponse({"detail": "认证凭据无效"}, status_code=401)
        return await call_next(request)


def _bearer_token() -> str:
    token = os.getenv(ENV_BEARER_TOKEN, "").strip()
    if not token:
        raise RuntimeError(
            f"auth_mode=bearer 要求配置非空 {ENV_BEARER_TOKEN}"
        )
    return token


def build_public_a2a_app(*, runtime, settings: PublicA2ASettings):
    """用同一Settings构建Card与JSON-RPC应用；bearer模式下加访问认证。"""
    app = build_jsonrpc_app(
        agent_card=build_agent_card(settings.public_base_url),
        agent_executor=HrAssistantExecutor(runtime),
        title="hr-assistant",
        health={
            "status": "ok",
            "agent": "hr-assistant",
            "version": "1.0.0",
            "protocol_version": "0.3.0",
            "auth_mode": settings.auth_mode,
        },
        request_handler_factory=PublicRequestHandler,
    )
    if settings.auth_mode == "bearer":
        app.add_middleware(BearerAuthMiddleware, token=_bearer_token())
    return app


def build_runtime():
    """从现有应用装配公共执行门面（复用业务路径，不复制路由）。"""
    from apps.orchestrator.public_runtime.runtime import HrAssistantRuntime
    from apps.orchestrator.public_runtime.attachments import AttachmentResolver

    application = _load_application()
    return HrAssistantRuntime(
        remote_router=application.remote_router,
        local_runner=_build_local_runner(application),
        leave_runner=_build_leave_runner(application),
        hr_context_builder=_build_hr_context_builder(),
        # 空 resolver registry 的真实 fail-closed 边界：由 resolver 自身在 resolve_all
        # 内先做数量/类型校验，再对支持类型返回 attachment_not_resolvable。
        attachment_resolver=AttachmentResolver(),
    )


def _build_hr_context_builder():
    """装配共享 HR execution context 构建器；生产必需配置缺失即启动失败。

    身份解析与 Gaia 凭据都来自服务端，不来自请求方 / session / 会话消息。
    """
    from packages.hr_domain.execution.context import build_hr_execution_context
    from packages.hr_domain.gaia.config import gaia_server_config_from_env
    from packages.hr_domain.gaia.provider import GaiaProvider
    from packages.hr_domain.identity import TrustedIdentityResolver

    resolver = TrustedIdentityResolver.from_env()
    config = gaia_server_config_from_env()
    provider = GaiaProvider(config)

    def builder(*, internal_user_id: str, request_id: str, context_id: str):
        return build_hr_execution_context(
            internal_user_id=internal_user_id,
            identity_resolver=resolver,
            gaia_config=config,
            gaia_provider=provider,
            request_id=request_id,
            context_id=context_id,
        )

    return builder


def _load_application():
    import agent as application_module

    return application_module._application


def _build_local_runner(application):
    from veadk import Runner
    from apps.orchestrator.public_runtime.runner import PublicLocalRunner

    root = application.root_agent
    return PublicLocalRunner(Runner(
        agent=root,
        app_name=root.name,
        short_term_memory=application.short_term_memory,
    ))


def _build_leave_runner(application):
    """构造独立本地 Leave runner：复用 application.leave_agent、共享 memory、相同 app_name。

    leave_agent 已是 root 的 child；用 ADK BaseAgent.clone() 得到 parent_agent=None 的
    独立 runner root，并设置 disallow_transfer_to_parent=True，避免 direct runner 再转回
    Root。不重新 new 模型配置，不读取新 env/key。
    """
    from veadk import Runner
    from apps.orchestrator.public_runtime.runner import PublicLocalRunner

    leave = application.leave_agent.clone()
    leave.parent_agent = None
    leave.disallow_transfer_to_parent = True
    return PublicLocalRunner(Runner(
        agent=leave,
        app_name=application.root_agent.name,
        short_term_memory=application.short_term_memory,
    ))


def run_local_server() -> None:
    import uvicorn

    settings = PublicA2ASettings.from_env()
    uvicorn.run(
        build_public_a2a_app(runtime=build_runtime(), settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
    )
