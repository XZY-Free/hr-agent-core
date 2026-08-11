"""hr-employee-data-agent公开AgentCard。"""

import os

from a2a.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill


AGENT_NAME = "hr-employee-data-agent"
AGENT_VERSION = "1.0.0"
LOCAL_BASE_URL = "http://127.0.0.1:8102"


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
    base_url = base_url or os.getenv(
        "HR_EMPLOYEE_DATA_A2A_BASE_URL", LOCAL_BASE_URL
    )
    return AgentCard(
        name=AGENT_NAME,
        description=(
            "Provides authenticated employees with their own leave balance, medical "
            "period, and annual leave calculation. Uses stub data in this deployment."
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
                "employee-leave-balance-query",
                "Employee Leave Balance Query",
                "Queries the authenticated employee's own leave balance.",
                ["hr", "employee-data", "leave-balance"],
            ),
            _skill(
                "employee-medical-period-query",
                "Employee Medical Period Query",
                "Queries the authenticated employee's own medical period.",
                ["hr", "employee-data", "medical-period"],
            ),
            _skill(
                "employee-annual-leave-calculation",
                "Employee Annual Leave Calculation",
                "Calculates the authenticated employee's own annual leave based on "
                "service years.",
                ["hr", "employee-data", "annual-leave"],
            ),
        ],
    )
