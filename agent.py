"""批次2单Runtime兼容装配入口：`uv run python agent.py`。

应用只提供构建函数；本入口完成一次性依赖注入并暴露AgentKit服务对象。
"""
from agentkit.apps import AgentkitAgentServerApp
from veadk.memory.short_term_memory import ShortTermMemory

from apps.consult_agent.agent import build_consult_agent
from apps.employee_data_agent.agent import build_employee_data_tools
from apps.orchestrator.agent import build_orchestrator
from apps.orchestrator.deployment.model_config import extra_config_for, model_for
from apps.orchestrator.local_leave.agent import build_leave_agent

employee_data_tools = build_employee_data_tools()
leave_agent = build_leave_agent(
    model_name=model_for("leave"),
    model_extra_config=extra_config_for("leave"),
)
consult_agent = build_consult_agent(
    model_name=model_for("consult"),
    model_extra_config=extra_config_for("consult"),
    employee_data_tools=employee_data_tools,
)
root_agent = build_orchestrator(
    model_name=model_for("root"),
    model_extra_config=extra_config_for("root"),
    leave_agent=leave_agent,
    consult_agent=consult_agent,
    employee_data_tools=employee_data_tools,
)

short_term_memory = ShortTermMemory(backend="local")
agent_server_app = AgentkitAgentServerApp(agent=root_agent, short_term_memory=short_term_memory)

if __name__ == "__main__":
    agent_server_app.run(host="0.0.0.0", port=8000)
