"""请假 Agent：受理请假申请、补齐信息、校验并提交请假单。"""
from datetime import date

from veadk import Agent

from hr_agent.agents.model_config import extra_config_for, model_for
from hr_agent.agents.prompts import LEAVE_AGENT_PROMPT
from hr_agent.tools.gaia.leave_query import get_leave_permissions, get_leave_balance
from hr_agent.tools.gaia.schedule_query import get_schedule
from hr_agent.tools.gaia.submit import submit_leave

# 今天日期注入 prompt，供模型换算口语日期（与 main_agent 同源）
TODAY = date.today().isoformat()

leave_agent = Agent(
    name="leave_agent",
    model_name=model_for("leave"),
    model_extra_config=extra_config_for("leave"),
    description="请假办理专员：受理请假申请、补齐信息、校验并提交请假单",
    instruction=LEAVE_AGENT_PROMPT.format(today=TODAY),
    tools=[get_leave_permissions, get_leave_balance, get_schedule, submit_leave],
)
