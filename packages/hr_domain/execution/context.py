"""Request-bound HR Execution Context。

在单次公共请求执行期间，通过 ContextVar 绑定：

- internal_user_id（伪匿名稳定ID）
- identity resolver（internal_user_id → employee_id / employee_ref）
- Gaia provider / server config
- 当前 request_id / context_id

业务工具需要当前员工身份时调用 require_employee_identity()；需要访问 Gaia 时
调用 require_gaia_provider()。语义要求：

- 问候 / 普通制度咨询不强制解析员工身份；
- 只有当 Leave / Employee Data 真正访问本人业务数据时才要求解析；
- 未映射返回 identity_unverified，严禁 fallback 到 user_id == employee_id；
- Galaxy 凭据只来自服务端 config，绝不进入 ToolResult。
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Protocol

from packages.hr_domain.gaia.config import GaiaServerConfig
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.identity import (
    IdentityResolutionError,
    TrustedIdentity,
    TrustedIdentityResolver,
)


class _IdentityProvider(Protocol):
    def resolve(self, user_id: str) -> TrustedIdentity: ...


@dataclass(frozen=True)
class HREXecutionContext:
    internal_user_id: str
    identity_resolver: _IdentityProvider
    gaia_config: GaiaServerConfig
    gaia_provider: GaiaProvider
    request_id: str
    context_id: str


# 当前请求维度绑定；无绑定（问候/制度咨询）时值为 None。
_HR_EXECUTION_CONTEXT: ContextVar[HREXecutionContext | None] = ContextVar(
    "hr_execution_context", default=None
)


def current_hr_context() -> HREXecutionContext | None:
    return _HR_EXECUTION_CONTEXT.get()


def require_hr_context() -> HREXecutionContext:
    ctx = _HR_EXECUTION_CONTEXT.get()
    if ctx is None:
        raise RuntimeError("HR执行上下文不存在")
    return ctx


def require_employee_identity() -> TrustedIdentity:
    """解析当前主体为可信员工身份。

    无绑定 context 或用户未映射都归为身份解析失败（identity_unverified），
    绝不以 user_id 冒充 employee_id，也绝不静默 fallback。
    """
    ctx = _HR_EXECUTION_CONTEXT.get()
    if ctx is None:
        raise IdentityResolutionError()
    try:
        return ctx.identity_resolver.resolve(ctx.internal_user_id)
    except IdentityResolutionError:
        raise


def require_gaia_provider() -> GaiaProvider:
    return require_hr_context().gaia_provider


@contextmanager
def bind_hr_execution_context(ctx: HREXecutionContext) -> Iterator[None]:
    """在一次请求执行期间绑定 HR execution context；结束后清理。

    同一请求内的多项工具调用共享同一绑定；不同请求之间互不继承。
    """
    token = _HR_EXECUTION_CONTEXT.set(ctx)
    try:
        yield
    finally:
        _HR_EXECUTION_CONTEXT.reset(token)


def build_hr_execution_context(
    *,
    internal_user_id: str,
    identity_resolver: TrustedIdentityResolver,
    gaia_config: GaiaServerConfig,
    gaia_provider: GaiaProvider,
    request_id: str,
    context_id: str,
) -> HREXecutionContext:
    return HREXecutionContext(
        internal_user_id=internal_user_id,
        identity_resolver=identity_resolver,
        gaia_config=gaia_config,
        gaia_provider=gaia_provider,
        request_id=request_id,
        context_id=context_id,
    )
