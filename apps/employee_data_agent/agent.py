"""员工本人数据应用的当前工具边界；独立Agent将在批次4建立。"""

from dataclasses import dataclass
from typing import Callable

from packages.hr_domain.gaia.employee_query import get_medical_period
from packages.hr_domain.gaia.leave_query import get_leave_balance
from packages.hr_domain.rules.annual_leave import calc_annual_leave


@dataclass(frozen=True)
class EmployeeDataTools:
    """供根兼容入口注入当前进程内Agent的本人数据工具。"""

    get_leave_balance: Callable
    get_medical_period: Callable
    calc_annual_leave: Callable


def build_employee_data_tools() -> EmployeeDataTools:
    """构造当前单Runtime使用的员工本人数据工具集合。"""
    return EmployeeDataTools(
        get_leave_balance=get_leave_balance,
        get_medical_period=get_medical_period,
        calc_annual_leave=calc_annual_leave,
    )
