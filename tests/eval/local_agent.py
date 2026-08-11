"""仅供原21条单进程基线评测使用的测试装配。

生产Orchestrator已固定通过A2A访问Consult与Employee Data；这里仅保留
原评测用例的本地基线执行能力，不会被运行时入口导入。
"""

from datetime import date

from veadk import Agent

from apps.consult_agent.agent import build_consult_agent
from apps.employee_data_agent.agent import build_employee_data_tools
from apps.orchestrator.callbacks.jump_marker import jump_marker_callback
from apps.orchestrator.local_leave.agent import build_leave_agent
from apps.orchestrator.prompts import MAIN_AGENT_PROMPT
from apps.orchestrator.routing.page_jump import page_jump
from packages.agent_runtime.model_config import extra_config_for, model_for
from packages.hr_domain.constants.phrases import PHRASES


def build_local_eval_agent() -> Agent:
    """使用原装配运行冻结的21条基线，不暴露为生产入口。"""
    employee_tools = build_employee_data_tools()
    leave = build_leave_agent(
        model_name=model_for("leave"),
        model_extra_config=extra_config_for("leave"),
    )
    consult = build_consult_agent(
        model_name=model_for("consult"),
        model_extra_config=extra_config_for("consult"),
    )
    return Agent(
        name="root_agent",
        model_name=model_for("root"),
        model_extra_config=extra_config_for("root"),
        description="人力 AI 助手入口：考勤请假分发、查询、页面跳转",
        instruction=MAIN_AGENT_PROMPT.format(today=date.today().isoformat(), **PHRASES),
        tools=[
            page_jump,
            employee_tools.get_leave_balance,
            employee_tools.get_medical_period,
            employee_tools.calc_annual_leave,
        ],
        sub_agents=[leave, consult],
        after_model_callback=jump_marker_callback,
    )


root_agent = build_local_eval_agent()
