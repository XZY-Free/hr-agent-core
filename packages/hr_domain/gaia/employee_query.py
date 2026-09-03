"""医疗期 / 员工在职信息查询工具。

签名保留 tool_context（veADK 框架注入），但不读取其中的凭据。员工身份由
request-bound HR execution context 可信解析；未映射返回 identity_unverified，
上下文/服务异常返回 gaia_error。
"""
from packages.hr_domain.schemas.tool_result import err
from packages.hr_domain.execution.context import (
    require_employee_identity,
    require_gaia_provider,
)
from packages.hr_domain.identity import IdentityResolutionError

_GAIA_ERR = "gaia_error"
_GAIA_ERR_MSG = "当前无法查询该业务，请联系管理员检查服务配置。"


def get_medical_period(tool_context) -> dict:
    """查询员工医疗期余额（quota/used/balance）。"""
    try:
        employee_id = require_employee_identity().employee_id
    except IdentityResolutionError:
        return err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    try:
        result = require_gaia_provider().medical_period(employee_id)
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    return result


def get_employee_info(tool_context) -> dict:
    """查询员工在职信息：性别、参工/本单位工龄、参工纪念日。"""
    try:
        employee_id = require_employee_identity().employee_id
    except IdentityResolutionError:
        return err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    try:
        result = require_gaia_provider().employee_info(employee_id)
    except Exception:
        return err(_GAIA_ERR, _GAIA_ERR_MSG)
    return result
