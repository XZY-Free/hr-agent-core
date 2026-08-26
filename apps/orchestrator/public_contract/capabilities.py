"""公共能力清单：能力=任务领域，不是函数调用入口。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicCapability:
    """一个公共能力域的稳定描述。"""

    key: str
    name_zh: str
    name_en: str
    description_zh: str
    description_en: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": {"zh-CN": self.name_zh, "en": self.name_en},
            "description": {"zh-CN": self.description_zh, "en": self.description_en},
        }


LEAVE_AND_ATTENDANCE_SERVICE = PublicCapability(
    key="leave-and-attendance-service",
    name_zh="假勤与请假服务",
    name_en="Leave and Attendance Service",
    description_zh=(
        "请假申请、请假修改相关对话、补登、假期类型理解、日期与时长理解、"
        "排班/余额/资格校验后的办理、提交前确认、失败后的继续沟通。"
    ),
    description_en=(
        "Leave requests, leave-modification conversations, retroactive entries, "
        "leave-type understanding, date and duration understanding, submission "
        "after schedule/balance/eligibility checks, pre-submit confirmation, and "
        "follow-up communication on failures."
    ),
)

EMPLOYEE_SELF_SERVICE = PublicCapability(
    key="employee-self-service",
    name_zh="员工本人信息服务",
    name_en="Employee Self-Service",
    description_zh=(
        "本人假期余额、本人医疗期、工龄信息、年假折算。"
    ),
    description_en=(
        "The employee's own leave balance, medical period, service years, and "
        "annual-leave proration."
    ),
)

HR_POLICY_AND_BENEFITS_CONSULTATION = PublicCapability(
    key="hr-policy-and-benefits-consultation",
    name_zh="人力制度与福利咨询",
    name_en="HR Policy and Benefits Consultation",
    description_zh=(
        "考勤制度、请假制度、入离职、试用期、薪酬、补贴、福利、地区差异类人力政策。"
    ),
    description_en=(
        "Attendance rules, leave policies, onboarding and offboarding, probation, "
        "compensation, allowances, benefits, and region-specific HR policies."
    ),
)

HR_SYSTEM_AND_DOCUMENT_ASSISTANCE = PublicCapability(
    key="hr-system-and-document-assistance",
    name_zh="人力系统与文档协助",
    name_en="HR System and Document Assistance",
    description_zh=(
        "人力系统操作说明、人力手册、人力文档问答、合法文档引用或附件辅助。"
    ),
    description_en=(
        "HR system operation guides, HR handbook help, HR document Q&A, and "
        "lawful document-reference or attachment assistance."
    ),
)

# 第一版冻结的四个公共能力域（顺序即展示顺序）。
PUBLIC_CAPABILITIES: tuple[PublicCapability, ...] = (
    LEAVE_AND_ATTENDANCE_SERVICE,
    EMPLOYEE_SELF_SERVICE,
    HR_POLICY_AND_BENEFITS_CONSULTATION,
    HR_SYSTEM_AND_DOCUMENT_ASSISTANCE,
)


def capabilities_payload() -> list[dict]:
    return [capability.to_dict() for capability in PUBLIC_CAPABILITIES]
