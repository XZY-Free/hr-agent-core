"""咨询 Agent：人力制度、政策与系统操作问题解答。"""
from veadk import Agent

from hr_agent.agents.model_config import extra_config_for, model_for
from hr_agent.agents.prompts import CONSULT_AGENT_PROMPT
from hr_agent.tools.rules.kb_search import kb_search
from hr_agent.tools.rules.parse_document import parse_document
from hr_agent.tools.gaia.leave_query import get_leave_balance
from hr_agent.tools.gaia.employee_query import get_medical_period
from hr_agent.tools.rules.annual_leave import calc_annual_leave

consult_agent = Agent(
    name="consult_agent",
    model_name=model_for("consult"),
    model_extra_config=extra_config_for("consult"),
    description="人力制度咨询专家：回答员工的人力制度、政策与系统操作问题",
    instruction=CONSULT_AGENT_PROMPT,
    tools=[kb_search, parse_document, get_leave_balance, get_medical_period, calc_annual_leave],
)
