"""WP-01 远端前置门禁的只读安全辅助。

范围：只做 AgentKit 只读控制面调用 + 只读 HTTPS 探测（health / agent-card）。
绝不：写云端、读取或打印凭据/AuthorizerConfiguration/响应正文、跟随 redirect、
向非公网地址发请求、用未发布配置兜底、回填 expected 镜像、访问 Gaia 接口。

安全：所有异常只输出「安全错误种类 / 白名单 error_code / HTTP 状态」；
env 只允许白名单键，且通过 before validator 直接压缩成枚举/布尔，原始值在任何模型里不可保存。
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentkit.sdk.runtime.client import AgentkitRuntimeClient
from agentkit.sdk.runtime.types import GetRuntimeRequest, GetRuntimeVersionRequest

# 固定探测上限（不可被调用方放大）
HTTP_TIMEOUT_SECONDS = 45
PUBLIC_CARD_VERSION = "1.0.0"
CARD_PROTOCOL_VERSION = "0.3.0"
CARD_PATH = "/.well-known/agent-card.json"
HEALTH_PATH = "/health"

EXPECTED_IMAGES_ENV = "HR_ACCEPTANCE_EXPECTED_IMAGES_JSON"
EXPECTED_IMAGE_KEYS = ("orchestrator", "consult", "employee_data")
VOLCENGINE_ACCESS_KEY_ENV = "VOLCENGINE_ACCESS_KEY"
VOLCENGINE_SECRET_KEY_ENV = "VOLCENGINE_SECRET_KEY"
VOLCENGINE_REGION_ENV = "VOLCENGINE_REGION"
VOLCENGINE_SESSION_TOKEN_ENV = "VOLCENGINE_SESSION_TOKEN"
DEFAULT_REGION = "cn-beijing"

# ---- inventory 选择：仅三个开发 Runtime，不含生产 existing-hr-agent ----
SELECTED_PURPOSES: dict[str, str] = {
    "orchestrator": "development-orchestrator",
    "consult": "development-consult-agent",
    "employee_data": "development-employee-data-agent",
}
EXPECTED_CARD_NAMES: dict[str, str] = {
    "orchestrator": "hr-assistant",
    "consult": "hr-consult-agent",
    "employee_data": "hr-employee-data-agent",
}
API_KEY_ENV: dict[str, str] = {
    "orchestrator": "HR_ACCEPTANCE_ORCHESTRATOR_API_KEY",
    "consult": "HR_ACCEPTANCE_CONSULT_API_KEY",
    "employee_data": "HR_ACCEPTANCE_EMPLOYEE_API_KEY",
}

# ---- env 白名单键 ----
GAIA_BACKEND_KEY = "GAIA_BACKEND"
EMPLOYEE_DATA_BACKEND_KEY = "EMPLOYEE_DATA_BACKEND"
KB_BACKEND_KEY = "KB_BACKEND"
GAIA_DRY_RUN_KEY = "GAIA_DRY_RUN"
GAIA_STUB_JSON_KEY = "GAIA_STUB_JSON"
EMPLOYEE_DATA_STUB_JSON_KEY = "EMPLOYEE_DATA_STUB_JSON"
IDENTITY_KEYS = ("EMPLOYEE_IDENTITY_MAP_JSON", "EMPLOYEE_REF_SECRET")
CONSULT_COLLECTION_KEYS = (
    "KB_COLLECTION_POLICY",
    "KB_COLLECTION_HANDBOOK",
    "KB_COLLECTION_SALARY",
    "KB_COLLECTION_CHILDCARE",
)
BACKEND_ENV_KEYS = (GAIA_BACKEND_KEY, EMPLOYEE_DATA_BACKEND_KEY, KB_BACKEND_KEY)
FLAG_ENV_KEYS = (GAIA_DRY_RUN_KEY,)
PRESENCE_ENV_KEYS = (
    GAIA_STUB_JSON_KEY,
    EMPLOYEE_DATA_STUB_JSON_KEY,
    *IDENTITY_KEYS,
    *CONSULT_COLLECTION_KEYS,
)

KNOWN_BACKENDS = frozenset({"gaia", "stub", "agentkit"})
KNOWN_FLAGS = frozenset({"true", "false"})
# 只允许回显这些 error_code；其余一律收敛成 sdk_error。
SAFE_ERROR_CODES = frozenset({
    "InvalidParameter", "InvalidParameter.UnknownParameter", "MissingParameter",
    "MissingParameter.Missing", "ResourceNotFound", "ResourceNotFound.NotFound",
    "InvalidResource", "InvalidResource.NotFound", "PermissionDenied",
    "PermissionDenied.NoPermission", "InvalidAccessKeyId", "InvalidAccessKey",
    "SignatureDoesNotMatch", "InvalidSignature", "ExpiredToken", "InvalidSecurityToken",
    "InvalidToken", "RequestExpired", "RequestLimitExceeded", "InternalError",
    "ServiceUnavailable", "InvalidRuntime", "InvalidRuntimeId", "InvalidRuntimeStatus",
    "InvalidVersion", "InvalidVersionNumber",
})


class _SafeBase(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class SafeEnvWhitelist(_SafeBase):
    """env 白名单摘要：后端枚举 + 布尔 flag + 必配键 presence bool，无原始值。"""

    backends: dict[str, str] = Field(default_factory=dict)
    flags: dict[str, str] = Field(default_factory=dict)
    present: dict[str, bool] = Field(default_factory=dict)


class SafeGetRuntime(_SafeBase):
    """GetRuntime 只需要名称/状态/当前版本；任何 Envs 都不保留。"""

    name: str | None = Field(default=None, alias="Name")
    status: str | None = Field(default=None, alias="Status")
    current_version_number: int | None = Field(default=None, alias="CurrentVersionNumber")


class SafeGetRuntimeVersion(_SafeBase):
    """GetRuntimeVersion：端点/发布镜像/发布状态 + env 白名单摘要。"""

    name: str | None = Field(default=None, alias="Name")
    status: str | None = Field(default=None, alias="Status")
    version_number: int | None = Field(default=None, alias="VersionNumber")
    artifact_type: str | None = Field(default=None, alias="ArtifactType")
    artifact_url: str | None = Field(default=None, alias="ArtifactUrl")
    endpoint: str | None = Field(default=None, alias="Endpoint")
    envs: SafeEnvWhitelist | None = Field(default=None, alias="Envs")

    @field_validator("envs", mode="before")
    @classmethod
    def _whitelist_envs(cls, raw):
        return _build_env_whitelist(raw)


class SafeAgentCard(_SafeBase):
    name: str | None = None
    version: str | None = None
    protocol_version: str | None = Field(default=None, alias="protocolVersion")
    url: str | None = None


@dataclass(frozen=True)
class ServiceTarget:
    key: str
    purpose: str
    runtime_name: str
    runtime_id: str
    expected_card_name: str
    api_key_env: str


@dataclass
class RuntimeProbe:
    """一次只读探测的安全结果。可变字段供 build_probe 填装，不含原始凭据/响应正文。"""

    key: str
    runtime_id: str
    runtime_name: str
    expected_card_name: str
    api_key_env: str
    blocker: str | None = None
    current_version: int | None = None
    published_version: int | None = None
    current_status: str | None = None
    published_status: str | None = None
    artifact_url: str | None = None
    endpoint: str | None = None
    endpoint_issue: str | None = None
    card_url_issue: str | None = None
    api_key_configured: bool = False
    health_status: int | None = None
    health_error: str | None = None
    card_status: int | None = None
    card_error: str | None = None
    card_name: str | None = None
    card_version: str | None = None
    card_protocol_version: str | None = None
    advertised_url_matches: bool | None = None
    backends: dict[str, str] = field(default_factory=dict)
    flags: dict[str, str] = field(default_factory=dict)
    present: dict[str, bool] = field(default_factory=dict)


# ---------------- inventory ----------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_service_targets() -> dict[str, ServiceTarget]:
    """从 deployment/resource-inventory.yaml 唯一选出三个开发 Runtime。"""
    inventory = _repo_root() / "deployment" / "resource-inventory.yaml"
    if not inventory.exists():
        raise FileNotFoundError(f"未找到 inventory: {inventory}")
    resources = (yaml.safe_load(inventory.read_text(encoding="utf-8")) or {}).get("resources") or []
    picked: dict[str, ServiceTarget] = {}
    for res in resources:
        if (res or {}).get("type") != "Runtime":
            continue
        purpose = str((res or {}).get("purpose") or "").strip()
        key = next((k for k, v in SELECTED_PURPOSES.items() if v == purpose), None)
        if key is None:
            continue
        if key in picked:
            raise ValueError(f"inventory 中 purpose={purpose} 有多个 Runtime，无法唯一确定")
        picked[key] = ServiceTarget(
            key=key,
            purpose=purpose,
            runtime_name=str((res or {}).get("name") or ""),
            runtime_id=str((res or {}).get("id") or ""),
            expected_card_name=EXPECTED_CARD_NAMES[key],
            api_key_env=API_KEY_ENV[key],
        )
    missing = [k for k in SELECTED_PURPOSES if k not in picked]
    if missing:
        raise ValueError("inventory 缺少开发 Runtime: " + ",".join(missing))
    return picked


# ---------------- expected 不可变镜像（严格、无回退） ----------------

def load_expected_images() -> dict[str, str]:
    """严格解析 HR_ACCEPTANCE_EXPECTED_IMAGES_JSON，返回 {服务: 不可变镜像}。

    - 未配置 / 空串 / 非法 JSON / 非对象 / 键集合不精确（缺或多）/ 值非字符串或空串
      一律明确失败（抛 RuntimeError），绝不回退到单一镜像或运行时发现状态；
    - 错误消息不携带任何镜像值 / 环境值，只输出固定安全越界描述，防止误回显。
    """
    raw = os.getenv(EXPECTED_IMAGES_ENV, "")
    if not raw.strip():
        raise RuntimeError(f"未配置 {EXPECTED_IMAGES_ENV}，无法绑定待验收不可变镜像")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"{EXPECTED_IMAGES_ENV} 不是合法 JSON") from None
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{EXPECTED_IMAGES_ENV} 必须是 JSON 对象")
    if set(parsed) != set(EXPECTED_IMAGE_KEYS):
        raise RuntimeError(f"{EXPECTED_IMAGES_ENV} 的键集合不精确匹配所需服务")
    result: dict[str, str] = {}
    for key in EXPECTED_IMAGE_KEYS:
        value = parsed[key]
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"{EXPECTED_IMAGES_ENV} 的每个值必须为非空字符串")
        result[key] = value.strip()
    return result


# ---------------- 客户端 ----------------

def build_agentkit_client() -> AgentkitRuntimeClient:
    access = os.getenv(VOLCENGINE_ACCESS_KEY_ENV, "").strip()
    secret = os.getenv(VOLCENGINE_SECRET_KEY_ENV, "").strip()
    if not access or not secret:
        raise RuntimeError(f"缺少 {VOLCENGINE_ACCESS_KEY_ENV} / {VOLCENGINE_SECRET_KEY_ENV}")
    return AgentkitRuntimeClient(
        access_key=access,
        secret_key=secret,
        region=os.getenv(VOLCENGINE_REGION_ENV, "").strip() or DEFAULT_REGION,
        session_token=os.getenv(VOLCENGINE_SESSION_TOKEN_ENV, "").strip(),
    )


# ---------------- env 白名单压缩 ----------------

def _build_env_whitelist(raw) -> SafeEnvWhitelist | None:
    """把原始 Envs 直接压缩成白名单摘要；未知枚举显示 unknown，不允许原始值进入模型。"""
    if not isinstance(raw, list):
        return None
    by_key: dict[str, object] = {}
    for item in raw:
        if isinstance(item, dict):
            key = str(item.get("Key") or "")
            if key:
                by_key[key] = item.get("Value")
    backends: dict[str, str] = {}
    for key in BACKEND_ENV_KEYS:
        val = str(by_key.get(key) or "").strip().lower()
        backends[key] = val if val in KNOWN_BACKENDS else "unknown"
    flags: dict[str, str] = {}
    for key in FLAG_ENV_KEYS:
        val = str(by_key.get(key) or "").strip().lower()
        flags[key] = val if val in KNOWN_FLAGS else "unknown"
    present: dict[str, bool] = {
        key: bool(str(by_key.get(key) or "").strip()) for key in PRESENCE_ENV_KEYS
    }
    return SafeEnvWhitelist(backends=backends, flags=flags, present=present)


# ---------------- 端点校验与 URL 规范化 ----------------

def _public_host_issue(host: str) -> str | None:
    if not host:
        return "endpoint_no_host"
    lower = host.lower()
    if lower in {"localhost", "0.0.0.0", "::1", "::"} or lower.startswith("127.") or lower.endswith(".local"):
        return "endpoint_loopback"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "endpoint_non_public_ip"
        return None
    # 公网 hostname 须是合理形态：含点、无空字符、无不安全字符。
    if "." not in lower or " " in lower or "_" in lower or ".." in lower:
        return "endpoint_unreasonable_host"
    return None


def endpoint_issue(url: str | None) -> str | None:
    """校验 URL 为公网 HTTPS 且无 credential/query/fragment/私有网段。"""
    if not url:
        return "endpoint_missing"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "endpoint_scheme_not_https"
    if parsed.username or parsed.password:
        return "endpoint_credential_in_url"
    if parsed.query:
        return "endpoint_has_query"
    if parsed.fragment:
        return "endpoint_has_fragment"
    return _public_host_issue(parsed.hostname or "")


def _normalize_url(url: str | None) -> str | None:
    """规范化完整 URL（仅尾斜杠归一），保留路径；无 scheme/host 返回 None。"""
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# ---------------- 安全错误分类 ----------------

def _classify_sdk_error(exc: BaseException) -> str:
    """只允许白名单 error_code，否则收敛成 sdk_error；不回显未知码/消息。"""
    code = getattr(exc, "error_code", None)
    if code and str(code) in SAFE_ERROR_CODES:
        return f"sdk_api:{code}"
    if type(exc).__name__ == "NetworkError":
        return "network_error"
    return "sdk_error"


# ---------------- 只读 HTTP ----------------

def _http_get(url: str, api_key: str):
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        return requests.get(url, headers=headers, allow_redirects=False, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return exc


def _fetch_health(endpoint: str, api_key: str) -> tuple[int | None, str | None]:
    resp = _http_get(endpoint.rstrip("/") + HEALTH_PATH, api_key)
    if isinstance(resp, requests.RequestException):
        return None, "network_error"
    return resp.status_code, None


def _fetch_card(endpoint: str, api_key: str) -> tuple[int | None, str | None, SafeAgentCard | None]:
    resp = _http_get(endpoint.rstrip("/") + CARD_PATH, api_key)
    if isinstance(resp, requests.RequestException):
        return None, "network_error", None
    if resp.status_code != 200:
        return resp.status_code, f"http_{resp.status_code}", None
    try:
        card = SafeAgentCard(**resp.json())
    except (ValueError, TypeError):
        return resp.status_code, "card_malformed", None
    return resp.status_code, None, card


# ---------------- 探测 ----------------

def build_probe(*, key: str, target: ServiceTarget, client: AgentkitRuntimeClient) -> RuntimeProbe:
    probe = RuntimeProbe(
        key=key,
        runtime_id=target.runtime_id,
        runtime_name=target.runtime_name,
        expected_card_name=target.expected_card_name,
        api_key_env=target.api_key_env,
    )
    api_key = os.getenv(target.api_key_env, "").strip()
    probe.api_key_configured = bool(api_key)

    if not target.runtime_id:
        probe.blocker = "runtime_id_missing"
        return probe
    try:
        current = client._invoke_api("GetRuntime", GetRuntimeRequest(runtime_id=target.runtime_id), SafeGetRuntime)
    except Exception as exc:  # noqa: BLE001
        probe.blocker = _classify_sdk_error(exc)
        return probe
    probe.current_version = current.current_version_number
    probe.current_status = current.status
    if current.current_version_number is None:
        probe.blocker = "runtime_current_version_missing"
        return probe
    try:
        version = client._invoke_api(
            "GetRuntimeVersion",
            GetRuntimeVersionRequest(runtime_id=target.runtime_id, version_number=current.current_version_number),
            SafeGetRuntimeVersion,
        )
    except Exception as exc:  # noqa: BLE001
        probe.blocker = _classify_sdk_error(exc)
        return probe
    probe.published_version = version.version_number
    probe.published_status = version.status
    probe.artifact_url = version.artifact_url  # 只用已发布配置，不做未发布兜底
    probe.endpoint = version.endpoint
    if version.envs is not None:
        probe.backends = version.envs.backends
        probe.flags = version.envs.flags
        probe.present = version.envs.present
    if version.artifact_url is None:
        probe.blocker = "published_artifact_missing"
        return probe
    if not version.endpoint:
        probe.blocker = "endpoint_missing"
        return probe
    probe.endpoint_issue = endpoint_issue(version.endpoint)
    if probe.endpoint_issue is not None:
        return probe  # 不发向不合规主机
    if not probe.api_key_configured:
        return probe
    probe.health_status, probe.health_error = _fetch_health(version.endpoint, api_key)
    card_status, card_error, card = _fetch_card(version.endpoint, api_key)
    probe.card_status = card_status
    probe.card_error = card_error
    if card is not None:
        probe.card_name = card.name
        probe.card_version = card.version
        probe.card_protocol_version = card.protocol_version
        probe.card_url_issue = endpoint_issue(card.url)
        probe.advertised_url_matches = (
            probe.card_url_issue is None
            and _normalize_url(card.url) == _normalize_url(version.endpoint)
        )
    return probe


def current_version(client: AgentkitRuntimeClient, runtime_id: str) -> int | None:
    """只读实时取当前版本号，用于版本前后一致门禁。"""
    if not runtime_id:
        return None
    try:
        current = client._invoke_api("GetRuntime", GetRuntimeRequest(runtime_id=runtime_id), SafeGetRuntime)
    except Exception:  # noqa: BLE001
        return None
    return current.current_version_number
