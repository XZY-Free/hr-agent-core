"""本地Orchestrator兼容入口与显式A2A transport装配。

应用只提供构建函数；本入口完成一次性依赖注入并暴露AgentKit服务对象。
"""
import os
from dataclasses import dataclass

from agentkit.apps import AgentkitAgentServerApp
from veadk.memory.short_term_memory import ShortTermMemory

from apps.consult_agent.agent import build_consult_agent
from apps.employee_data_agent.agent import build_employee_data_tools
from apps.orchestrator.agent import build_orchestrator
from apps.orchestrator.a2a.middleware import DeterministicA2AMiddleware
from apps.orchestrator.a2a.router import OrchestratorRemoteRouter
from apps.orchestrator.a2a.routing import transport_mode
from apps.orchestrator.local_leave.agent import build_leave_agent
from packages.agent_runtime.model_config import extra_config_for, model_for


@dataclass
class AgentApplication:
    employee_data_tools: object
    leave_agent: object
    consult_agent: object
    root_agent: object
    short_term_memory: object
    agent_server_app: object
    remote_router: object | None


def build_agent_application(
    *,
    consult_transport: str | None = None,
    employee_data_transport: str | None = None,
    a2a_client=None,
) -> AgentApplication:
    consult_transport = transport_mode(
        "HR_CONSULT_TRANSPORT",
        consult_transport or os.getenv("HR_CONSULT_TRANSPORT", "local"),
    )
    employee_data_transport = transport_mode(
        "HR_EMPLOYEE_DATA_TRANSPORT",
        employee_data_transport or os.getenv("HR_EMPLOYEE_DATA_TRANSPORT", "local"),
    )
    employee_tools = build_employee_data_tools()
    leave = build_leave_agent(
        model_name=model_for("leave"),
        model_extra_config=extra_config_for("leave"),
    )
    consult = build_consult_agent(
        model_name=model_for("consult"),
        model_extra_config=extra_config_for("consult"),
    )
    root = build_orchestrator(
        model_name=model_for("root"),
        model_extra_config=extra_config_for("root"),
        leave_agent=leave,
        consult_agent=consult,
        employee_data_tools=employee_tools,
        consult_transport=consult_transport,
        employee_data_transport=employee_data_transport,
    )
    memory = ShortTermMemory(backend="local")
    server = AgentkitAgentServerApp(agent=root, short_term_memory=memory)
    remote_router = None
    if "a2a" in {consult_transport, employee_data_transport}:
        async def session_exists(*, user_id: str, session_id: str) -> bool:
            session = await memory.session_service.get_session(
                app_name=root.name,
                user_id=user_id,
                session_id=session_id,
            )
            return session is not None

        remote_router = OrchestratorRemoteRouter(
            consult_transport=consult_transport,
            employee_data_transport=employee_data_transport,
            client=a2a_client,
            session_exists=session_exists,
            consult_url=os.getenv("HR_CONSULT_A2A_URL", "http://127.0.0.1:8101"),
            employee_data_url=os.getenv(
                "HR_EMPLOYEE_DATA_A2A_URL", "http://127.0.0.1:8102"
            ),
        )
        server.app.add_middleware(DeterministicA2AMiddleware, router=remote_router)
    return AgentApplication(
        employee_data_tools=employee_tools,
        leave_agent=leave,
        consult_agent=consult,
        root_agent=root,
        short_term_memory=memory,
        agent_server_app=server,
        remote_router=remote_router,
    )


_application = build_agent_application()
employee_data_tools = _application.employee_data_tools
leave_agent = _application.leave_agent
consult_agent = _application.consult_agent
root_agent = _application.root_agent
short_term_memory = _application.short_term_memory
agent_server_app = _application.agent_server_app

if __name__ == "__main__":
    agent_server_app.run(host="0.0.0.0", port=8000)
