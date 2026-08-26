"""公共执行主体适配：SnowHarness ExecutionSubject → 内部可信 user_id。

不做平台主体→employee_id 的业务映射；员工业务身份解析仍由现有
TrustedIdentityResolver 在员工数据智能体内部完成。本层只负责：
1. 平台主体命名空间隔离（用户自然语言不能创建 trusted subject）；
2. 无主体时的匿名身份（制度咨询仍可运行，本人数据由下游稳定拒绝）；
3. 不接受任何 employee_id / corp_id 形态的输入。
"""

import hmac
import hashlib

from apps.orchestrator.public_runtime.request import ExecutionSubject

ANONYMOUS_USER_ID = "public-anonymous"

# 内部可信 user_id 前缀：与员工数据智能体的身份映射表（user_id→employee_id）
# 对接；SnowHarness 侧永远只见 execution_subject.subject_id。
_SUBJECT_NAMESPACE = "snowharness"


class PublicIdentityAdapter:
    def internal_user_id(self, subject: ExecutionSubject | None) -> str:
        if subject is None:
            return ANONYMOUS_USER_ID
        digest = hmac.new(
            _SUBJECT_NAMESPACE.encode(),
            subject.subject_id.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        return f"{_SUBJECT_NAMESPACE}-{digest}"
