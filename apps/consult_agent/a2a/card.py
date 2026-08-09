"""hr-consult-agent公开AgentCard。"""

from a2a.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill


AGENT_NAME = "hr-consult-agent"
AGENT_VERSION = "1.0.0"
LOCAL_BASE_URL = "http://127.0.0.1:8101"


def _skill(
    skill_id: str,
    name: str,
    description: str,
    tags: list[str],
) -> AgentSkill:
    return AgentSkill(
        id=skill_id,
        name=name,
        description=description,
        tags=tags,
        input_modes=["text"],
        output_modes=["text"],
    )


def build_agent_card(base_url: str = LOCAL_BASE_URL) -> AgentCard:
    """构造协议0.3.0、JSON-RPC、支持SSE的非敏感AgentCard。"""
    return AgentCard(
        name=AGENT_NAME,
        description=(
            "回答人力制度、政策、考勤、薪酬福利、系统操作和文档内容问题；"
            "不查询员工本人数据，不办理请假"
        ),
        version=AGENT_VERSION,
        protocol_version="0.3.0",
        preferred_transport="JSONRPC",
        url=f"{base_url.rstrip('/')}/",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        provider=AgentProvider(
            organization="HR Agent Team",
            url=base_url.rstrip("/"),
        ),
        skills=[
            _skill(
                "hr-policy-consultation",
                "人力制度咨询",
                "回答考勤、休假、入离职和试用期等制度问题",
                ["人力制度", "考勤", "休假", "入离职", "试用期"],
            ),
            _skill(
                "hr-benefit-consultation",
                "薪酬福利咨询",
                "回答薪酬、津贴、福利及相关制度问题",
                ["薪酬", "津贴", "福利"],
            ),
            _skill(
                "hr-system-operation-guide",
                "人事系统操作指引",
                "回答人事系统和操作手册问题",
                ["人事系统", "操作手册", "考勤系统"],
            ),
            _skill(
                "hr-document-question-answering",
                "人力文档问答",
                "解析用户提供的人力文档链接并回答文档内容",
                ["人力文档", "文档解析", "摘要"],
            ),
        ],
    )
