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
    consult_transport: str = "local",
    employee_data_transport: str = "local",
) -> Agent:
    """通过显式依赖注入装配当前进程内子Agent和查询工具。"""
    today = date.today().isoformat()
    instruction = MAIN_AGENT_PROMPT.format(today=today, **PHRASES)
    if consult_transport not in {"local", "a2a"}:
        raise RuntimeError("HR_CONSULT_TRANSPORT仅支持local或a2a")
    if employee_data_transport not in {"local", "a2a"}:
        raise RuntimeError("HR_EMPLOYEE_DATA_TRANSPORT仅支持local或a2a")
    tools = [page_jump]
    if employee_data_transport == "local":
        tools.extend([
            employee_data_tools.get_leave_balance,
            employee_data_tools.get_medical_period,
            employee_data_tools.calc_annual_leave,
        ])
    sub_agents = [leave_agent]
    if consult_transport == "local":
        sub_agents.append(consult_agent)
    return Agent(
        name="root_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="人力 AI 助手入口：考勤请假分发、查询、页面跳转",
        instruction=instruction,
        tools=tools,
        sub_agents=sub_agents,
        after_model_callback=jump_marker_callback,
    )
