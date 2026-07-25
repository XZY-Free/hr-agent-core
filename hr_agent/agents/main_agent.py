"""主 Agent（root_agent）：入口分发 + 查询工具 + 页面跳转 + 跳转标记回调。

- sub_agents 挂载 leave_agent（请假办理）、consult_agent（制度咨询）
- tools 挂载查询类工具与 page_jump（不重复挂载 leave_agent 内部的 submit/排班等工具）
- after_model_callback 挂 jump_marker_callback：把 pending_jump 注入为 `[[JUMP:<code>]]`
"""
import os

from veadk import Agent

from hr_agent.agents.leave_agent import leave_agent
from hr_agent.agents.consult_agent import consult_agent
from hr_agent.agents.prompts import MAIN_AGENT_PROMPT
from hr_agent.callbacks.jump_marker import jump_marker_callback
from hr_agent.constants.phrases import PHRASES
from hr_agent.tools.gaia.employee_query import get_medical_period
from hr_agent.tools.gaia.leave_query import get_leave_balance
from hr_agent.tools.rules.annual_leave import calc_annual_leave
from hr_agent.tools.rules.page_jump import page_jump

MODEL_NAME = os.getenv("MODEL_AGENT_NAME", "doubao-seed-1.6-250615")

# 用 PHRASES 注入固定话术占位符 {cancel_leave}/{handoff}
INSTRUCTION = MAIN_AGENT_PROMPT.format(**PHRASES)

root_agent = Agent(
    name="root_agent",
    model_name=MODEL_NAME,
    description="人力 AI 助手入口：考勤请假分发、查询、页面跳转",
    instruction=INSTRUCTION,
    tools=[page_jump, get_leave_balance, get_medical_period, calc_annual_leave],
    sub_agents=[leave_agent, consult_agent],
    after_model_callback=jump_marker_callback,
)
