"""hr-consult-agent公开AgentCard。"""

import os

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


def build_agent_card(base_url: str | None = None) -> AgentCard:
    """构造协议0.3.0、JSON-RPC、支持SSE的非敏感AgentCard。"""
    base_url = base_url or os.getenv("HR_CONSULT_A2A_BASE_URL", LOCAL_BASE_URL)
    return AgentCard(
        name=AGENT_NAME,
        description=(
            "Answers HR policy, attendance, compensation, benefits, HR system "
            "operation, and HR document questions. Does not access personal "
            "employee data or process leave requests."
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
                "HR Policy Consultation",
                "Answers questions about attendance, leave policies, onboarding, "
                "offboarding, and probation rules.",
                ["hr", "policy", "attendance", "leave-policy"],
            ),
            _skill(
                "hr-benefit-consultation",
                "HR Benefits Consultation",
                "Answers questions about compensation, allowances, and employee "
                "benefits.",
                ["hr", "compensation", "benefits"],
            ),
            _skill(
                "hr-system-operation-guide",
                "HR System Operation Guide",
                "Provides guidance for HR system operations and handbook procedures.",
                ["hr", "system", "operations"],
            ),
            _skill(
                "hr-document-question-answering",
                "HR Document Question Answering",
                "Parses HR document links and answers questions based on document "
                "content.",
                ["hr", "document", "question-answering"],
            ),
        ],
    )
