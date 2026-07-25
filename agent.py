"""AgentKit 服务入口：`uv run python agent.py` 起 0.0.0.0:8000。

对齐官方 hello_world 形态：
- agent_server_app 暴露给 AgentKit Runtime 加载
- __main__ 直接 run
"""
from agentkit.apps import AgentkitAgentServerApp
from veadk.memory.short_term_memory import ShortTermMemory

from hr_agent.agents.main_agent import root_agent

short_term_memory = ShortTermMemory(backend="local")
agent_server_app = AgentkitAgentServerApp(agent=root_agent, short_term_memory=short_term_memory)

if __name__ == "__main__":
    agent_server_app.run(host="0.0.0.0", port=8000)
