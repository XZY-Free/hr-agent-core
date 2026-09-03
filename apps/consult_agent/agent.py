"""当前单Runtime中的咨询Agent构建入口。"""

from veadk import Agent

from apps.consult_agent.prompts import CONSULT_AGENT_PROMPT
from apps.consult_agent.tools.attendance_calculation import attendance_calculation
from apps.consult_agent.tools.kb_search import kb_search
from apps.consult_agent.tools.parse_document import parse_document
from packages.agent_runtime.user_input import INPUT_REQUEST_INSTRUCTION, request_user_input


def build_consult_agent(
    *,
    model_name: str,
    model_extra_config: dict,
) -> Agent:
    """按冻结顺序构造只包含咨询工具的独立Consult Agent。"""
    return Agent(
        name="hr_consult_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="人力制度咨询专家：回答员工的人力制度、政策与系统操作问题",
        instruction=CONSULT_AGENT_PROMPT + INPUT_REQUEST_INSTRUCTION,
        tools=[kb_search, parse_document, attendance_calculation, request_user_input],
    )
