"""咨询 Agent 结构测试。"""
from agent import consult_agent
from apps.consult_agent.tools.kb_search import kb_search
from apps.consult_agent.tools.parse_document import parse_document
from packages.hr_domain.gaia.leave_query import get_leave_balance
from packages.hr_domain.gaia.employee_query import get_medical_period
from packages.hr_domain.rules.annual_leave import calc_annual_leave


def _tool_names(agent) -> set:
    return {getattr(t, "__name__", getattr(t, "name", "")) for t in agent.tools}


def test_consult_agent_basic():
    assert consult_agent.name == "consult_agent"
    assert consult_agent.model_name
    assert consult_agent.instruction and "人力" in consult_agent.instruction


def test_consult_agent_tools():
    names = _tool_names(consult_agent)
    expected = {
        "kb_search",
        "parse_document",
        "get_leave_balance",
        "get_medical_period",
        "calc_annual_leave",
    }
    assert expected <= names
