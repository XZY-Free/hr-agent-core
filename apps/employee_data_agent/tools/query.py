"""只向模型公开的两个Employee Data只读工具。"""

from contextlib import contextmanager
from contextvars import ContextVar

from apps.employee_data_agent.provider import EmployeeDataProvider


_request_binding: ContextVar[tuple[EmployeeDataProvider, str] | None] = ContextVar(
    "employee_data_request_binding",
    default=None,
)


@contextmanager
def bind_employee_request(provider: EmployeeDataProvider, employee_id: str):
    token = _request_binding.set((provider, employee_id))
    try:
        yield
    finally:
        _request_binding.reset(token)


def _binding() -> tuple[EmployeeDataProvider, str]:
    value = _request_binding.get()
    if value is None:
        raise RuntimeError("Employee Data请求上下文不存在")
    return value


def calc_annual_leave(tool_context) -> dict:
    """查询当前员工工龄、年假档位、折算结果及年假余额。"""
    provider, employee_id = _binding()
    return provider.annual_profile(employee_id).to_tool_result()


def get_medical_period(tool_context) -> dict:
    """查询当前员工医疗期额度、已用及余额。"""
    provider, employee_id = _binding()
    return provider.medical_period(employee_id).to_tool_result()
