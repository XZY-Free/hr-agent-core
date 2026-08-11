"""基于官方A2AFastAPIApplication的本地JSON-RPC与SSE服务。"""

from typing import TYPE_CHECKING

from apps.consult_agent.a2a.card import LOCAL_BASE_URL, build_agent_card
from apps.consult_agent.a2a.executor import ConsultAgentExecutor
from packages.agent_runtime.a2a.server import build_jsonrpc_app

if TYPE_CHECKING:
    from apps.consult_agent.runtime import ConsultRuntime


def build_a2a_app(runtime: "ConsultRuntime | None" = None):
    if runtime is None:
        from apps.consult_agent.runtime import build_consult_runtime

        runtime = build_consult_runtime()
    return build_jsonrpc_app(
        agent_card=build_agent_card(),
        agent_executor=ConsultAgentExecutor(runtime),
        title="hr-consult-agent",
        health={"status": "ok", "agent": "hr-consult-agent", "version": "1.0.0"},
    )


def run_local_server() -> None:
    import uvicorn

    uvicorn.run(build_a2a_app(), host="127.0.0.1", port=8101)


def run_cloud_server() -> None:
    import uvicorn

    uvicorn.run(build_a2a_app(), host="0.0.0.0", port=8000)
