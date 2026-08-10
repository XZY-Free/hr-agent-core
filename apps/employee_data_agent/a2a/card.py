"""hr-employee-data-agent公开AgentCard。"""

from a2a.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill


AGENT_NAME = "hr-employee-data-agent"
AGENT_VERSION = "1.0.0"
LOCAL_BASE_URL = "http://127.0.0.1:8102"


def _skill(skill_id: str, name: str, description: str) -> AgentSkill:
    return AgentSkill(
        id=skill_id,
        name=name,
        description=description,
        tags=["当前员工", "本人数据", "只读"],
        input_modes=["text"],
        output_modes=["text"],
    )


def build_agent_card(base_url: str = LOCAL_BASE_URL) -> AgentCard:
    return AgentCard(
        name=AGENT_NAME,
        description=(
            "查询当前员工本人的假期余额、医疗期、工龄与年假折算，只读；"
            "不解释制度，不办理请假，不查询其他员工。"
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
            _skill("employee-leave-balance-query", "本人假期余额查询", "查询当前员工本人的假期余额"),
            _skill("employee-medical-period-query", "本人医疗期查询", "查询当前员工本人的医疗期"),
            _skill(
                "employee-annual-leave-calculation",
                "本人年假折算",
                "查询当前员工工龄并计算本人年假档位与折算结果",
            ),
        ],
    )
