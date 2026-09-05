"""服务端 Gaia 凭据与租户配置 — 共享 Authority。

Gaia corp/secret/grant_type/schedule_tenant 只来自服务端环境变量，绝不来自
请求方、session state 或会话消息。缺少生产必需配置时 fail closed；stub 只能
显式开启，不能自动 fallback，也不自动把缺配置当 stub。

配置边界：
- GAIA_BACKEND=gaia（默认）：四项真实 Gaia 凭据必须齐全，否则 GaiaConfigError。
- GAIA_BACKEND=stub：仅允许干跑；不读取/不要求真实 Gaia 凭据，返回字段为空的
  GaiaServerConfig（只在显式 stub 下可用；GaiaProvider 在 stub 下不会构造 GaiaClient）。
- 未知 backend：fail closed，不回落 stub。
"""

import os
from dataclasses import dataclass

_TRUE_DRY_RUN = frozenset({"true", "1", "yes"})


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


def _dry_run_enabled() -> bool:
    return os.getenv("GAIA_DRY_RUN", "true").strip().lower() in _TRUE_DRY_RUN


def gaia_server_config_from_env() -> GaiaServerConfig:
    """按 GAIA_BACKEND 构建共享 Gaia 配置；stub 不强制真实凭据，gaia 缺配置即 fail closed。"""
    backend = os.getenv("GAIA_BACKEND", "gaia").strip().lower()
    if backend == "stub":
        if not _dry_run_enabled():
            raise GaiaConfigError(
                "GAIA Stub只允许用于干跑开发环境（GAIA_DRY_RUN=true）"
            )
        # 显式 stub：不要求真实 Gaia 凭据；字段留空仅供 stub 轨迹，绝不构造 GaiaClient。
        return GaiaServerConfig(
            corp_id="", client_secret="", grant_type="", schedule_tenant=""
        )
    if backend != "gaia":
        raise GaiaConfigError("GAIA_BACKEND仅支持gaia或stub")
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
