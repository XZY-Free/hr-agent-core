"""基于官方A2AFastAPIApplication的本地JSON-RPC与SSE服务。"""

from typing import TYPE_CHECKING

from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore

from apps.consult_agent.a2a.card import LOCAL_BASE_URL, build_agent_card
from apps.consult_agent.a2a.executor import ConsultAgentExecutor

if TYPE_CHECKING:
    from apps.consult_agent.runtime import ConsultRuntime


def build_a2a_app(runtime: "ConsultRuntime | None" = None):
    if runtime is None:
        from apps.consult_agent.runtime import build_consult_runtime

        runtime = build_consult_runtime()
    handler = DefaultRequestHandler(
        agent_executor=ConsultAgentExecutor(runtime),
        task_store=InMemoryTaskStore(),
    )
    app = A2AFastAPIApplication(
        agent_card=build_agent_card(),
        http_handler=handler,
    ).build(title="hr-consult-agent")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "agent": "hr-consult-agent", "version": "1.0.0"}

    return app


def run_local_server() -> None:
    import uvicorn

    uvicorn.run(build_a2a_app(), host="127.0.0.1", port=8101)
