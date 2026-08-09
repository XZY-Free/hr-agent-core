"""当前单Runtime中的本地请假Agent构建入口。"""

from datetime import date

from veadk import Agent

from apps.orchestrator.local_leave.prompts import LEAVE_AGENT_PROMPT
from apps.orchestrator.local_leave.submit import submit_leave
from packages.hr_domain.gaia.leave_query import (
    get_leave_balance,
    get_leave_permissions,
)
from packages.hr_domain.gaia.schedule_query import get_schedule


def build_leave_agent(*, model_name: str, model_extra_config: dict) -> Agent:
    """按冻结工具顺序构造本地请假Agent。"""
    today = date.today().isoformat()
    return Agent(
        name="leave_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="请假办理专员：受理请假申请、补齐信息、校验并提交请假单",
        instruction=LEAVE_AGENT_PROMPT.format(today=today),
        tools=[get_leave_permissions, get_leave_balance, get_schedule, submit_leave],
    )
