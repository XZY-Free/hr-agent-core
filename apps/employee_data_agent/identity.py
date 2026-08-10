"""服务端可信身份映射；A2A user_id绝不直接作为employeeId。"""

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field


class IdentityResolutionError(RuntimeError):
    def __init__(self, error_code: str = "identity_unverified"):
        self.error_code = error_code
        super().__init__("当前身份无法完成本人数据查询")


@dataclass(frozen=True)
class TrustedIdentity:
    employee_id: str = field(repr=False)
    employee_ref: str


class TrustedIdentityResolver:
    def __init__(self, mapping: dict[str, str], *, ref_secret: str):
        clean = {
            str(user).strip(): str(employee).strip()
            for user, employee in mapping.items()
            if str(user).strip() and str(employee).strip()
        }
        if not clean or not ref_secret.strip():
            raise ValueError("可信身份映射和employee_ref密钥不能为空")
        self._mapping = clean
        self._ref_secret = ref_secret.encode()

    def resolve(self, user_id: str) -> TrustedIdentity:
        employee_id = self._mapping.get(user_id)
        if not employee_id:
            raise IdentityResolutionError()
        digest = hmac.new(
            self._ref_secret,
            employee_id.encode(),
            hashlib.sha256,
        ).hexdigest()
        return TrustedIdentity(employee_id=employee_id, employee_ref=f"empref_{digest}")

    @classmethod
    def from_env(cls) -> "TrustedIdentityResolver":
        raw = os.getenv("EMPLOYEE_IDENTITY_MAP_JSON", "")
        secret = os.getenv("EMPLOYEE_REF_SECRET", "")
        try:
            mapping = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise RuntimeError("员工身份映射配置无效") from None
        if not isinstance(mapping, dict):
            raise RuntimeError("员工身份映射配置无效")
        try:
            return cls(mapping, ref_secret=secret)
        except ValueError as exc:
            raise RuntimeError("员工身份映射配置无效") from exc
