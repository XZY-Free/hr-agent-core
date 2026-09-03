"""员工本人数据的本地工具集合与独立Agent构建入口。"""

from dataclasses import dataclass
from typing import Callable

from veadk import Agent

from apps.employee_data_agent.prompts import EMPLOYEE_DATA_AGENT_PROMPT
from apps.employee_data_agent.tools import (
    calc_annual_leave as agent_calc_annual_leave,
    get_leave_balances as agent_get_leave_balances,
    get_medical_period as agent_get_medical_period,
)


@dataclass(frozen=True)
class EmployeeDataTools:
    """供本地兼容入口注入当前进程内Agent的本人数据工具。"""

    get_leave_balances: Callable
    get_medical_period: Callable
    calc_annual_leave: Callable
    get_leave_balance: Callable


def build_employee_data_tools() -> EmployeeDataTools:
    """构造当前单Runtime使用的员工本人数据工具集合（均为共享只读工具）。"""
    return EmployeeDataTools(
        get_leave_balances=agent_get_leave_balances,
        get_medical_period=agent_get_medical_period,
        calc_annual_leave=agent_calc_annual_leave,
        get_leave_balance=agent_get_leave_balances,
    )


def build_employee_data_agent(*, model_name: str, model_extra_config: dict) -> Agent:
    return Agent(
        name="hr_employee_data_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="只读查询当前员工本人的各假种余额、医疗期、工龄与年假折算",
        instruction=EMPLOYEE_DATA_AGENT_PROMPT,
        tools=[agent_calc_annual_leave, agent_get_medical_period, agent_get_leave_balances],
    )
