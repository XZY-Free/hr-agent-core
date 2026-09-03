"""兼容 re-export：Employee Data 身份解析已上移到共享 Authority。

生产代码必须使用 packages.hr_domain.identity；本文件仅为既有引用提供迁移期的
薄别名，不定义第二套 resolver。
"""

from packages.hr_domain.identity import (  # noqa: F401
    IdentityResolutionError,
    TrustedIdentity,
    TrustedIdentityResolver,
)

__all__ = ["IdentityResolutionError", "TrustedIdentity", "TrustedIdentityResolver"]
