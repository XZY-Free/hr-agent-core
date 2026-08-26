"""公共执行主体适配：SnowHarness ExecutionSubject → 内部可信 user_id。

只做pseudonymous namespace conversion：不是authentication，也不是trust。
不做平台主体→employee_id 的业务映射；员工业务身份解析仍由现有
TrustedIdentityResolver 在员工数据智能体内部完成。本层只负责：
1. 平台主体命名空间隔离（用户自然语言不能创建 trusted subject）；
2. 确定性内部ID（operator可离线用 public_subject_ref.py 生成同一映射键）；
3. 无主体时的匿名身份（制度咨询仍可运行，本人数据由下游稳定拒绝）；
4. 不接受任何 employee_id / corp_id 形态的输入。
"""

import hashlib

from apps.orchestrator.public_runtime.request import ExecutionSubject

ANONYMOUS_USER_ID = "public-anonymous"

# 内部可信 user_id 前缀：与员工数据智能体的身份映射表
# （internal_user_id → employee_id，EMPLOYEE_IDENTITY_MAP_JSON）对接；
# SnowHarness 侧永远只见 execution_subject.subject_id。
_SUBJECT_NAMESPACE = "snowharness"


def derive_internal_user_id(subject_kind: str, subject_id: str) -> str:
    """固定internal_user_id算法（无密钥、确定性、可离线复算）。

    canonical = namespace + "\\0" + subject_kind + "\\0" + subject_id
    internal_user_id = "snowharness-" + sha256(canonical)前32个hex
    """
    canonical = (
        f"{_SUBJECT_NAMESPACE}\0{subject_kind}\0{subject_id}"
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:32]
    return f"{_SUBJECT_NAMESPACE}-{digest}"


class PublicIdentityAdapter:
    def internal_user_id(self, subject: ExecutionSubject | None) -> str:
        if subject is None:
            return ANONYMOUS_USER_ID
        return derive_internal_user_id(
            subject.subject_kind, subject.subject_id
        )
