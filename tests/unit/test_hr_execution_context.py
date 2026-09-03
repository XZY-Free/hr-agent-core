"""Request-bound HR Execution Context 语义测试。

验证 WP-01 核心身份链：问候不要求身份；确实访问本人业务数据时才解析；解析
失败返回 identity_unverified 且不访问 Gaia；解析成功工具收到正确员工；同一
请求内多次调用共享绑定，不同请求间不继承。
"""

from types import SimpleNamespace
import pytest

from packages.hr_domain.execution.context import (
    HREXecutionContext,
    bind_hr_execution_context,
    current_hr_context,
    require_employee_identity,
    require_gaia_provider,
    require_hr_context,
)
from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.identity import IdentityResolutionError, TrustedIdentityResolver


def _config():
    return GaiaServerConfig(
        corp_id="corp1", client_secret="sec", grant_type="client_credentials",
        schedule_tenant="snowbeertest",
    )


def _resolver():
    return TrustedIdentityResolver({"user-alpha": "EMP-001"}, ref_secret="unit-secret")


def _provider():
    return GaiaProvider(_config())


def _ctx(user_id="user-alpha"):
    return HREXecutionContext(
        internal_user_id=user_id,
        identity_resolver=_resolver(),
        gaia_config=_config(),
        gaia_provider=_provider(),
        request_id="req-a",
        context_id="ctx-a",
    )


def test_no_binding_current_context_is_none():
    assert current_hr_context() is None
    with pytest.raises(RuntimeError, match="HR执行上下文不存在"):
        require_hr_context()


def test_greeting_without_identity_does_not_require_resolution():
    # 问候只读公共 context；不调用 require_employee_identity 则不会触发解析。
    # 即使无绑定，只要工具不访问本人数据，就不失败。
    with bind_hr_execution_context(_ctx()):
        assert require_hr_context().internal_user_id == "user-alpha"
        # 未调用 require_employee_identity，因此问候可完成（此处仅断言不抛错）。
    # 退出绑定后 context 清理。
    assert current_hr_context() is None


def test_resolved_identity_returns_correct_employee():
    with bind_hr_execution_context(_ctx()):
        identity = require_employee_identity()
    assert identity.employee_id == "EMP-001"
    assert "EMP-001" not in identity.employee_ref


def test_unmapped_fails_closed_identity_unverified():
    with bind_hr_execution_context(_ctx(user_id="unknown-user")):
        with pytest.raises(IdentityResolutionError):
            require_employee_identity()


def test_gaia_provider_is_shared_from_context():
    with bind_hr_execution_context(_ctx()):
        provider = require_gaia_provider()
    assert isinstance(provider, GaiaProvider)
    assert provider.config.corp_id == "corp1"


def test_same_request_shares_binding():
    with bind_hr_execution_context(_ctx()):
        first = require_employee_identity()
        second = require_employee_identity()
    assert first.employee_id == second.employee_id == "EMP-001"


def test_identity_state_not_inherited_across_requests():
    # 两个独立请求各自绑定；第二个请求不应继承第一个的身份实例状态。
    with bind_hr_execution_context(_ctx(user_id="user-alpha")):
        first = require_employee_identity()
    with bind_hr_execution_context(_ctx(user_id="unknown-user")):
        with pytest.raises(IdentityResolutionError):
            require_employee_identity()
    assert first.employee_id == "EMP-001"


def test_identity_never_falls_back_to_user_id():
    # 未映射时绝不把 user_id 当 employee_id（不是默认/测试员工）。
    with bind_hr_execution_context(_ctx(user_id="unknown-user")):
        try:
            require_employee_identity()
            assert False
        except IdentityResolutionError as exc:
            assert exc.error_code == "identity_unverified"
            assert "unknown-user" not in str(exc)


def test_identity_unverified_does_not_call_gaia(monkeypatch):
    """身份未映射时，业务工具在解析阶段即失败，绝不访问 Gaia。"""
    from packages.hr_domain.gaia.leave_query import get_leave_balance

    def _boom(*args, **kwargs):
        raise AssertionError("身份未解析时不应访问 Gaia")

    monkeypatch.setattr(GaiaProvider, "leave_balance", _boom)
    ctx = HREXecutionContext(
        internal_user_id="unknown-user",
        identity_resolver=_resolver(),
        gaia_config=_config(),
        gaia_provider=_provider(),
        request_id="req-a",
        context_id="ctx-a",
    )
    with bind_hr_execution_context(ctx):
        result = get_leave_balance("年休假", SimpleNamespace(state={}))
    assert result["success"] is False
    assert result["error_type"] == "identity_unverified"
