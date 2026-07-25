"""请假 Agent：受理请假申请、补齐信息、校验并提交请假单。"""
import os

from veadk import Agent

from hr_agent.agents.prompts import LEAVE_AGENT_PROMPT
from hr_agent.tools.gaia.leave_query import get_leave_permissions, get_leave_balance
from hr_agent.tools.gaia.schedule_query import get_schedule
from hr_agent.tools.gaia.submit import submit_leave

MODEL_NAME = os.getenv("MODEL_AGENT_NAME", "doubao-seed-1.6-250615")

leave_agent = Agent(
    name="leave_agent",
    model_name=MODEL_NAME,
    description="请假办理专员：受理请假申请、补齐信息、校验并提交请假单",
    instruction=LEAVE_AGENT_PROMPT,
    tools=[get_leave_permissions, get_leave_balance, get_schedule, submit_leave],
)
