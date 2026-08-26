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
    )
    if settings.auth_mode == "bearer":
        app.add_middleware(BearerAuthMiddleware, token=_bearer_token())
    return app


def build_runtime():
    """从现有应用装配公共执行门面（复用业务路径，不复制路由）。"""
    from apps.orchestrator.public_runtime.runtime import HrAssistantRuntime

    application = _load_application()
    return HrAssistantRuntime(
        remote_router=application.remote_router,
        local_runner=_build_local_runner(application),
    )


def _load_application():
    import agent as application_module

    return application_module._application


def _build_local_runner(application):
    from veadk import Runner

    root = application.root_agent
    return Runner(
        agent=root,
        app_name=root.name,
        short_term_memory=application.short_term_memory,
    )


def run_local_server() -> None:
    import uvicorn

    settings = PublicA2ASettings.from_env()
    uvicorn.run(
        build_public_a2a_app(runtime=build_runtime(), settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
    )
