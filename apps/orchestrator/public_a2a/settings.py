"""公共A2A端点与运行配置的唯一Authority。

listen_host / listen_port / public_base_url / auth_mode 只在这里解析，
card、server、generator 一律通过显式传入的 settings 取值，
禁止各自读取不同的环境变量或维护第二默认。
"""

import os
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8100
DEFAULT_PUBLIC_URL = "http://127.0.0.1:8100"
DEFAULT_AUTH_MODE = "none"

AUTH_MODES = ("none", "bearer")

ENV_HOST = "HR_ASSISTANT_A2A_HOST"
ENV_PORT = "HR_ASSISTANT_A2A_PORT"
ENV_PUBLIC_URL = "HR_ASSISTANT_A2A_PUBLIC_URL"
ENV_AUTH_MODE = "HR_ASSISTANT_A2A_AUTH_MODE"
# bearer模式下必填的Runtime Access Credential（只证明调用权）。
ENV_BEARER_TOKEN = "HR_ASSISTANT_A2A_BEARER_TOKEN"


class SettingsError(ValueError):
    """端点/运行配置非法。"""


def normalize_public_base_url(raw: str) -> str:
    """规范公共基础URL：去尾slash、仅http/https、禁query/fragment。"""
    url = (raw or "").strip().rstrip("/")
    if not url:
        raise SettingsError("public URL 不能为空")
    if "://" not in url:
        raise SettingsError("public URL 必须包含 http:// 或 https://")
    scheme, _, rest = url.partition("://")
    if scheme not in ("http", "https"):
        raise SettingsError(f"public URL 只允许 http/https，收到:{scheme}")
    if not rest:
        raise SettingsError("public URL 缺少主机与端口")
    if "?" in url or "#" in url:
        raise SettingsError("public URL 禁止携带 query 或 fragment")
    return url


@dataclass(frozen=True)
class PublicA2ASettings:
    """一次进程装配的端点与访问配置快照。"""

    listen_host: str
    listen_port: int
    public_base_url: str
    auth_mode: str

    @property
    def card_url(self) -> str:
        """AgentCard.url：公共基础URL规范化后加根路径。"""
        return f"{normalize_public_base_url(self.public_base_url)}/"

    @classmethod
    def from_env(cls, env=None) -> "PublicA2ASettings":
        """从环境读取并校验；测试与装配入口显式调用，不做import时冻结。"""
        source = env if env is not None else os.environ
        host = source.get(ENV_HOST) or DEFAULT_HOST
        port_raw = source.get(ENV_PORT) or str(DEFAULT_PORT)
        try:
            port = int(port_raw)
        except ValueError:
            raise SettingsError(f"{ENV_PORT} 必须是整数，收到:{port_raw!r}") from None
        if not (0 < port < 65536):
            raise SettingsError(f"{ENV_PORT} 越界:{port}")
        if host == "0.0.0.0" and not source.get(ENV_PUBLIC_URL):
            raise SettingsError(
                "监听 0.0.0.0 时必须显式配置 HR_ASSISTANT_A2A_PUBLIC_URL"
                "（0.0.0.0 不是可通告地址）"
            )
        public_url = source.get(ENV_PUBLIC_URL) or DEFAULT_PUBLIC_URL
        auth_mode = source.get(ENV_AUTH_MODE) or DEFAULT_AUTH_MODE
        if auth_mode not in AUTH_MODES:
            raise SettingsError(
                f"{ENV_AUTH_MODE} 只允许 none/bearer，收到:{auth_mode!r}"
            )
        return cls(
            listen_host=host,
            listen_port=port,
            public_base_url=normalize_public_base_url(public_url),
            auth_mode=auth_mode,
        )
