"""当前单Runtime中的Orchestrator构建入口。"""

from datetime import date

from veadk import Agent

from apps.orchestrator.callbacks.jump_marker import jump_marker_callback
from apps.orchestrator.prompts import MAIN_AGENT_PROMPT
from apps.orchestrator.routing.page_jump import page_jump
from packages.hr_domain.constants.phrases import PHRASES


def build_orchestrator(
    *,
    model_name: str,
    model_extra_config: dict,
    leave_agent,
    consult_agent,
    employee_data_tools,
) -> Agent:
    """通过显式依赖注入装配当前进程内子Agent和查询工具。"""
    today = date.today().isoformat()
    instruction = MAIN_AGENT_PROMPT.format(today=today, **PHRASES)
    return Agent(
        name="root_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="人力 AI 助手入口：考勤请假分发、查询、页面跳转",
        instruction=instruction,
        tools=[
            page_jump,
            employee_data_tools.get_leave_balance,
            employee_data_tools.get_medical_period,
            employee_data_tools.calc_annual_leave,
        ],
        sub_agents=[leave_agent, consult_agent],
        after_model_callback=jump_marker_callback,
    )
