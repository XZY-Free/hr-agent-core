"""Employee Data可信身份解析与不可逆引用测试。"""

import pytest

from apps.employee_data_agent.identity import (
    IdentityResolutionError,
    TrustedIdentityResolver,
)


@pytest.fixture
def resolver():
    return TrustedIdentityResolver(
        {"user-alpha": "EMP-001", "user-beta": "EMP-002"},
        ref_secret="unit-test-ref-secret",
    )


def test_trusted_mapping_returns_stable_opaque_employee_ref(resolver):
    first = resolver.resolve("user-alpha")
    second = resolver.resolve("user-alpha")
    other = resolver.resolve("user-beta")

    assert first.employee_id == "EMP-001"
    assert first.employee_ref == second.employee_ref
    assert first.employee_ref != other.employee_ref
    assert "EMP-001" not in first.employee_ref
    assert "EMP-001" not in repr(first)


def test_user_id_is_never_used_as_employee_id_without_mapping(resolver):
    with pytest.raises(IdentityResolutionError) as exc_info:
        resolver.resolve("EMP-001")
    assert exc_info.value.error_code == "identity_unverified"
    assert "EMP-001" not in str(exc_info.value)


def test_empty_mapping_or_secret_fails_closed():
    with pytest.raises(ValueError):
        TrustedIdentityResolver({}, ref_secret="unit-test-ref-secret")
    with pytest.raises(ValueError):
        TrustedIdentityResolver({"user": "EMP-001"}, ref_secret="")
