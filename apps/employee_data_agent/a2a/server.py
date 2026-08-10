"""Employee Data官方JSON-RPC与SSE本地服务。"""

from typing import TYPE_CHECKING

from apps.employee_data_agent.a2a.card import build_agent_card
from apps.employee_data_agent.a2a.executor import EmployeeDataAgentExecutor
from packages.agent_runtime.a2a.server import build_jsonrpc_app

if TYPE_CHECKING:
    from apps.employee_data_agent.runtime import EmployeeDataRuntime


def build_a2a_app(runtime: "EmployeeDataRuntime | None" = None):
    if runtime is None:
        from apps.employee_data_agent.runtime import build_employee_data_runtime

        runtime = build_employee_data_runtime()
    return build_jsonrpc_app(
        agent_card=build_agent_card(),
        agent_executor=EmployeeDataAgentExecutor(runtime),
        title="hr-employee-data-agent",
        health={
            "status": "ok",
            "agent": "hr-employee-data-agent",
            "version": "1.0.0",
        },
    )


def run_local_server() -> None:
    import uvicorn

    uvicorn.run(build_a2a_app(), host="127.0.0.1", port=8102)
