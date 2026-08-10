"""官方A2A FastAPI应用的通用启动装配。"""

from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore


def build_jsonrpc_app(*, agent_card, agent_executor, title: str, health: dict):
    handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=InMemoryTaskStore(),
    )
    app = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler,
    ).build(title=title)

    @app.get("/health")
    async def health_check() -> dict:
        return dict(health)

    return app
