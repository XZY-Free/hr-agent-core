"""Request-bound HR Execution Context。"""

from packages.hr_domain.execution.context import (  # noqa: F401
    HREXecutionContext,
    IdentityResolutionError,
    TrustedIdentity,
    bind_hr_execution_context,
    build_hr_execution_context,
    current_hr_context,
    require_employee_identity,
    require_gaia_provider,
    require_hr_context,
)

__all__ = [
    "HREXecutionContext",
    "IdentityResolutionError",
    "TrustedIdentity",
    "bind_hr_execution_context",
    "build_hr_execution_context",
    "current_hr_context",
    "require_employee_identity",
    "require_gaia_provider",
    "require_hr_context",
]
