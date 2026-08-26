"""企业人力智能助手顶层AgentCard（SnowHarness 唯一可见身份）。"""

from a2a.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill

from apps.orchestrator.public_contract.capabilities import PUBLIC_CAPABILITIES
from apps.orchestrator.public_contract.identity import (
    PUBLIC_AGENT_ID,
    PUBLIC_AGENT_NAME_EN,
    PUBLIC_AGENT_VERSION,
)
from apps.orchestrator.public_contract.interaction import STREAMING_TRANSPORT
from apps.orchestrator.public_contract.result_contract import ERROR_CODES

def build_agent_card(base_url: str) -> AgentCard:
    """构造顶层公共AgentCard；卡片能力=任务领域，不暴露内部拓扑。

    base_url 由唯一 Settings Authority（public_a2a.settings）提供；
    本模块不再读取环境变量，也不存在第二默认端点。
    """
    return AgentCard(
        name=PUBLIC_AGENT_ID,
        description=(
            f"{PUBLIC_AGENT_NAME_EN}: leave and attendance requests, employee "
            "self-service data, HR policy and benefits consultation, and HR "
            "system/document assistance. Input-required (waiting for user "
            "supplements) is supported; incremental token streaming is not "
            f"provided (event streaming only). Error codes: {', '.join(ERROR_CODES)}."
        ),
        version=PUBLIC_AGENT_VERSION,
        protocol_version="0.3.0",
        preferred_transport="JSONRPC",
        url=f"{base_url.rstrip('/')}/",
        capabilities=AgentCapabilities(streaming=STREAMING_TRANSPORT),
        default_input_modes=["text"],
        default_output_modes=["text"],
        provider=AgentProvider(
            organization="HR Agent Team",
            url=base_url.rstrip("/"),
        ),
        skills=[
            AgentSkill(
                id=capability.key,
                name=capability.name_en,
                description=capability.description_en,
                tags=["hr", capability.key],
                input_modes=["text"],
                output_modes=["text"],
            )
            for capability in PUBLIC_CAPABILITIES
        ],
    )
