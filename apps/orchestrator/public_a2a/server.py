"""顶层公共A2A服务：AgentCard、JSON-RPC端点与健康检查。

公共合同是运营方导入SnowHarness的显式请求工件（生成器产物），
远程运行时不暴露合同发现端点。
"""

from packages.agent_runtime.a2a.server import build_jsonrpc_app

from apps.orchestrator.public_a2a.card import build_agent_card
from apps.orchestrator.public_a2a.executor import HrAssistantExecutor


def build_public_a2a_app(*, runtime, base_url: str | None = None):
    app = build_jsonrpc_app(
        agent_card=build_agent_card(base_url),
        agent_executor=HrAssistantExecutor(runtime),
        title="hr-assistant",
        health={
            "status": "ok",
            "agent": "hr-assistant",
            "version": "1.0.0",
        },
    )

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

    uvicorn.run(
        build_public_a2a_app(runtime=build_runtime()),
        host="127.0.0.1",
        port=8100,
    )
