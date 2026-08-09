"""当前单Runtime中的咨询Agent构建入口。"""

from veadk import Agent

from apps.consult_agent.prompts import CONSULT_AGENT_PROMPT
from apps.consult_agent.tools.kb_search import kb_search
from apps.consult_agent.tools.parse_document import parse_document


def build_consult_agent(
    *,
    model_name: str,
    model_extra_config: dict,
    employee_data_tools,
) -> Agent:
    """注入员工本人数据工具并按冻结顺序构造咨询Agent。"""
    return Agent(
        name="consult_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="人力制度咨询专家：回答员工的人力制度、政策与系统操作问题",
        instruction=CONSULT_AGENT_PROMPT,
        tools=[
            kb_search,
            parse_document,
            employee_data_tools.get_leave_balance,
            employee_data_tools.get_medical_period,
            employee_data_tools.calc_annual_leave,
        ],
    )
