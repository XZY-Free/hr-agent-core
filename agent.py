"""本地Orchestrator兼容入口与显式A2A transport装配。

应用只提供构建函数；本入口完成一次性依赖注入并暴露AgentKit服务对象。
"""
import os
from dataclasses import dataclass

from agentkit.apps import AgentkitAgentServerApp
from veadk.memory.short_term_memory import ShortTermMemory

from apps.orchestrator.agent import build_orchestrator
from apps.orchestrator.a2a.middleware import DeterministicA2AMiddleware
from apps.orchestrator.a2a.router import OrchestratorRemoteRouter
from apps.orchestrator.local_leave.agent import build_leave_agent
from packages.agent_runtime.a2a.client import OfficialA2AClient
from packages.agent_runtime.model_config import extra_config_for, model_for
from packages.hr_domain.documents.context import session_document_context


@dataclass
class AgentApplication:
    leave_agent: object
    root_agent: object
    short_term_memory: object
    agent_server_app: object
    remote_router: object


def build_agent_application(
    *,
    a2a_client=None,
) -> AgentApplication:
    leave = build_leave_agent(
        model_name=model_for("leave"),
        model_extra_config=extra_config_for("leave"),
    )
    root = build_orchestrator(
        model_name=model_for("root"),
        model_extra_config=extra_config_for("root"),
        leave_agent=leave,
    )
    memory = ShortTermMemory(backend="local")
    server = AgentkitAgentServerApp(agent=root, short_term_memory=memory)
    consult_url = os.getenv("HR_CONSULT_A2A_URL", "http://127.0.0.1:8101")
    employee_data_url = os.getenv(
        "HR_EMPLOYEE_DATA_A2A_URL", "http://127.0.0.1:8102"
    )
    if a2a_client is None:
        a2a_client = OfficialA2AClient(
            timeout_seconds=float(os.getenv("HR_A2A_TIMEOUT_SECONDS", "30")),
            runtime_api_keys={
                consult_url: os.getenv("HR_CONSULT_RUNTIME_API_KEY", ""),
                employee_data_url: os.getenv(
                    "HR_EMPLOYEE_DATA_RUNTIME_API_KEY", ""
                ),
            },
        )

    async def session_exists(*, user_id: str, session_id: str) -> bool:
        session = await memory.session_service.get_session(
            app_name=root.name,
            user_id=user_id,
            session_id=session_id,
        )
        if session is not None:
            return True
        # 新会话首条消息：幂等预建 root session，使确定性远程路由从第一条
        # 消息起生效（否则首条咨询类问题被门控拦回本地 root，而 root 无
        # consult 本地子 Agent，会 transfer 失败）。create_session 幂等，
        # 不写入任何状态；context_summary 对空 session 返回空串。
        await memory.session_service.create_session(
            app_name=root.name,
            user_id=user_id,
            session_id=session_id,
        )
        return True

    async def context_summary_provider(
        *, user_id: str, session_id: str, message: str
    ) -> str:
        session = await memory.session_service.get_session(
            app_name=root.name,
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            return ""
        return session_document_context(getattr(session, "state", None), message)

    remote_router = OrchestratorRemoteRouter(
        client=a2a_client,
        session_exists=session_exists,
        context_summary_provider=context_summary_provider,
        consult_url=consult_url,
        employee_data_url=employee_data_url,
    )
    server.app.add_middleware(DeterministicA2AMiddleware, router=remote_router)
    return AgentApplication(
        leave_agent=leave,
        root_agent=root,
        short_term_memory=memory,
        agent_server_app=server,
        remote_router=remote_router,
    )


_application = build_agent_application()
leave_agent = _application.leave_agent
root_agent = _application.root_agent
short_term_memory = _application.short_term_memory
agent_server_app = _application.agent_server_app

if __name__ == "__main__":
    agent_server_app.run(host="0.0.0.0", port=8000)
