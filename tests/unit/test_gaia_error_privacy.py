"""后台配置缺失不是员工需要填写的业务信息，不把内部字段交给模型追问。

WP-01：gaia 工具不再从 session state 读取凭据；无 request-bound HR execution
context 或身份未映射时 fail closed，返回 identity_unverified / gaia_error，且不
泄露 corp_id / secret / grant_type。
"""

from types import SimpleNamespace
import pytest

from packages.hr_domain.gaia.schedule_query import get_schedule
from packages.hr_domain.gaia.leave_query import get_leave_balance, get_leave_permissions
from packages.hr_domain.gaia.employee_query import get_medical_period, get_employee_info
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.execution.context import (
    HREXecutionContext,
    bind_hr_execution_context,
)
from packages.hr_domain.identity import TrustedIdentityResolver

CTX = SimpleNamespace(state={})


def _config():
    return GaiaServerConfig(
        corp_id="corp-secret", client_secret="client-secret",
        grant_type="client_credentials", schedule_tenant="snowbeertest",
    )


def _bind_context(user_id="user-alpha"):
    config = _config()
    ctx = HREXecutionContext(
        internal_user_id=user_id,
        identity_resolver=TrustedIdentityResolver(
            {"user-alpha": "E001"}, ref_secret="unit-secret"),
        gaia_config=config,
        gaia_provider=GaiaProvider(config),
        request_id="req-a",
        context_id="ctx-a",
    )
    return bind_hr_execution_context(ctx)


@pytest.mark.parametrize("tool,args", [
    (get_schedule, ("2026-08-29", "2026-08-29")),
    (get_leave_balance, ("年休假",)), (get_leave_permissions, ()),
    (get_medical_period, ()), (get_employee_info, ()),
])
def test_no_binding_fails_closed_identity_unverified(tool, args):
    result = tool(*args, CTX)
    assert result["success"] is False
    assert result["error_type"] == "identity_unverified"
    assert "corp-secret" not in result["message"]
    assert "client-secret" not in result["message"]


def test_missing_config_reports_safe_failure_without_credentials(monkeypatch):
    # 生产配置缺失 fail closed，且不把内部字段名/凭据暴露给工具结果
    from packages.hr_domain.gaia.config import gaia_server_config_from_env
    for name in ["GAIA_CORP_ID", "GAIA_CLIENT_SECRET", "GAIA_GRANT_TYPE",
                 "GAIA_SCHEDULE_TENANT"]:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="Gaia服务端配置缺失"):
        gaia_server_config_from_env()
