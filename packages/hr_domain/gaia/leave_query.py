"""假期余额 / 可申请假期类型查询工具。

签名保留 tool_context（veADK 框架注入），但不再读取其中的凭据。员工身份由
request-bound HR execution context 通过共享 Gaia Provider 可信解析；未映射返回
identity_unverified，上下文/服务异常返回 gaia_error，绝不信任 session state 或
模型提供的值，也绝不 fallback 到 user_id == employee_id。
"""
from packages.hr_domain.schemas.tool_result import err
from packages.hr_domain.execution.context import (
    require_employee_identity,
    require_gaia_provider,
)
from packages.hr_domain.identity import IdentityResolutionError

_GAIA_ERR = "gaia_error"
_GAIA_ERR_MSG = "当前无法查询该业务，请联系管理员检查服务配置。"


def get_leave_balance(leave_type: str, tool_context) -> dict:
    """查询员工假期余额。

    Args:
        leave_type: 假期类型名称（如"年休假"）；传空字符串返回全部假期余额。
    """
    try:
        employee_id = require_employee_identity().employee_id
    except IdentityResolutionError:
        return err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    try:
        result = require_gaia_provider().leave_balance(leave_type, employee_id)
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    return result


def get_leave_permissions(tool_context) -> dict:
    """查询员工可申请的假期类型列表（假期权限）。"""
    try:
        employee_id = require_employee_identity().employee_id
    except IdentityResolutionError:
        return err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    try:
        result = require_gaia_provider().leave_permissions(employee_id)
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    return result
