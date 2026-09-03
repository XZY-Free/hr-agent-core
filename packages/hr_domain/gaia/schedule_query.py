"""排班查询工具。

签名保留 tool_context（veADK 框架注入），但不读取其中的凭据。员工身份由
request-bound HR execution context 可信解析；租户来自服务端 GAIA_SCHEDULE_TENANT，
不再在代码中写死 snowbeertest。未映射返回 identity_unverified，异常返回 gaia_error。
"""
from packages.hr_domain.schemas.tool_result import err
from packages.hr_domain.execution.context import (
    require_employee_identity,
    require_gaia_provider,
)
from packages.hr_domain.identity import IdentityResolutionError

_GAIA_ERR = "gaia_error"
_GAIA_ERR_MSG = "当前无法查询排班，请联系管理员检查服务配置。"


def get_schedule(start_date: str, end_date: str, tool_context) -> dict:
    """查询员工排班数据。

    Args:
        start_date: 起始日期 yyyy-MM-dd
        end_date: 结束日期 yyyy-MM-dd
    """
    try:
        employee_id = require_employee_identity().employee_id
    except IdentityResolutionError:
        return err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    try:
        result = require_gaia_provider().schedule(start_date, end_date, employee_id)
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    return result
