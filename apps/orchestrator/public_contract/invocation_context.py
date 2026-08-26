"""调用上下文合同（Invocation Context Contract）。

合同声明的是调用整个智能体时平台可以/应该提供哪些通用上下文；
不是业务参数表，严禁 Tool 化设计。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextItem:
    """一个调用上下文种类的合同描述。"""

    key: str
    name_zh: str
    necessity: str  # preferred | accepted
    description_zh: str
    applies_to: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        payload = {
            "key": self.key,
            "name": {"zh-CN": self.name_zh},
            "necessity": self.necessity,
            "description": {"zh-CN": self.description_zh},
        }
        if self.applies_to:
            payload["applies_to"] = list(self.applies_to)
        return payload


EXECUTION_SUBJECT = ContextItem(
    key="execution_subject",
    name_zh="执行主体",
    necessity="preferred",
    description_zh=(
        "SnowHarness本次执行所代表的可信调用者身份。制度咨询不一定需要身份；"
        "本人信息/请假办理需要身份。有可信身份且策略允许时尽量提供；没有身份时"
        "普通制度咨询仍可运行，本人数据或办理业务由智能体返回稳定身份缺失结果，"
        "不允许用户输入员工工号冒充可信身份。"
    ),
    applies_to=(
        "leave-and-attendance-service",
        "employee-self-service",
    ),
)

TIMEZONE = ContextItem(
    key="timezone",
    name_zh="时区",
    necessity="preferred",
    description_zh=(
        "用于“明天”“后天”“下周三”等相对日期和跨时区日期理解。"
    ),
)

CURRENT_DATETIME = ContextItem(
    key="current_datetime",
    name_zh="当前时间",
    necessity="preferred",
    description_zh=(
        "本次执行的可信当前日期/时间。当前日期/时间在每次执行时确定，"
        "不在服务启动时冻结；如提供则优先使用。"
    ),
)

LOCALE = ContextItem(
    key="locale",
    name_zh="语言区域",
    necessity="preferred",
    description_zh="正式支持语言为zh-CN。",
)

CONVERSATION_SUMMARY = ContextItem(
    key="conversation_summary",
    name_zh="对话摘要",
    necessity="preferred",
    description_zh=(
        "只在当前任务需要前文、平台有合法摘要、数据策略允许时提供。"
        "优先摘要/引用，不默认把整个会话历史全量复制给外部智能体。"
    ),
)

ATTACHMENT_REFERENCES = ContextItem(
    key="attachment_references",
    name_zh="附件引用",
    necessity="accepted",
    description_zh=(
        "主要服务人力系统与文档协助。只在当前任务相关、调用方有权访问、"
        "合同允许、数据策略允许时发送引用；不默认把所有附件发送给智能体。"
    ),
    applies_to=("hr-system-and-document-assistance",),
)

# 第一版调用上下文合同条目。
INVOCATION_CONTEXT_ITEMS: tuple[ContextItem, ...] = (
    EXECUTION_SUBJECT,
    TIMEZONE,
    CURRENT_DATETIME,
    LOCALE,
    CONVERSATION_SUMMARY,
    ATTACHMENT_REFERENCES,
)

# 合同允许的上下文键（运行时校验公共请求使用）。
ALLOWED_CONTEXT_KEYS = frozenset(
    item.key for item in INVOCATION_CONTEXT_ITEMS
)


def invocation_context_payload() -> list[dict]:
    return [item.to_dict() for item in INVOCATION_CONTEXT_ITEMS]
