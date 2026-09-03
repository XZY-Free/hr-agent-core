"""服务端 Gaia 凭据与租户配置 — 共享 Authority。

Gaia corp/secret/grant_type/schedule_tenant 只来自服务端环境变量，绝不来自
请求方、session state 或会话消息。缺少生产必需配置时 fail closed；stub 只能
显式开启，不能自动 fallback。
"""

import os
from dataclasses import dataclass


class GaiaConfigError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)
        self.error_code = "gaia_config_error"


@dataclass(frozen=True)
class GaiaServerConfig:
    corp_id: str
    client_secret: str
    grant_type: str
    schedule_tenant: str


def gaia_server_config_from_env() -> GaiaServerConfig:
    """从服务端环境变量构造 Gaia 生产配置；缺失即 fail closed。"""
    values = {
        "corp_id": os.getenv("GAIA_CORP_ID", "").strip(),
        "client_secret": os.getenv("GAIA_CLIENT_SECRET", "").strip(),
        "grant_type": os.getenv("GAIA_GRANT_TYPE", "").strip(),
        "schedule_tenant": os.getenv("GAIA_SCHEDULE_TENANT", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise GaiaConfigError(
            "Gaia服务端配置缺失: " + ", ".join(missing)
        )
    return GaiaServerConfig(**values)
