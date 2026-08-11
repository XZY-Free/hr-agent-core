"""AgentKit Runtime来源A2A注册的AgentCard ASCII门禁。"""

from collections.abc import Iterator
from typing import Any

from a2a.types import AgentCard

from apps.consult_agent.a2a.card import build_agent_card as build_consult_card
from apps.employee_data_agent.a2a.card import (
    build_agent_card as build_employee_data_card,
)


CONSULT_URL = "https://consult.example.invalid"
EMPLOYEE_DATA_URL = "https://employee.example.invalid"


def _string_leaves(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
        return
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _string_leaves(key, f"{path}.<key>")
            yield from _string_leaves(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _string_leaves(child, f"{path}[{index}]")


def _assert_registration_ready(card: AgentCard, expected_url: str) -> None:
    payload = card.model_dump(mode="json", by_alias=True, exclude_none=True)
    validated = AgentCard.model_validate(payload)
    assert validated == card

    invalid = [
        (path, value)
        for path, value in _string_leaves(payload)
        if any(not 0x20 <= ord(character) <= 0x7E for character in value)
    ]
    assert invalid == []

    skill_ids = [skill.id for skill in card.skills]
    assert len(skill_ids) == len(set(skill_ids))

    security_schemes = set((payload.get("securitySchemes") or {}).keys())
    for requirement in payload.get("security") or []:
        assert set(requirement).issubset(security_schemes)

    assert card.url == f"{expected_url}/"
    assert card.url.startswith("https://")
    serialized = card.model_dump_json(by_alias=True, exclude_none=True)
    assert all(blocked not in serialized for blocked in (
        "127.0.0.1", "localhost", "8101", "8102", "test-runtime-api-key"
    ))


def test_consult_agent_card_is_agentkit_registration_ready():
    card = build_consult_card(CONSULT_URL)

    _assert_registration_ready(card, CONSULT_URL)
    assert card.description == (
        "Answers HR policy, attendance, compensation, benefits, HR system "
        "operation, and HR document questions. Does not access personal "
        "employee data or process leave requests."
    )
    assert [
        (skill.id, skill.name, skill.description, skill.tags, skill.examples)
        for skill in card.skills
    ] == [
        (
            "hr-policy-consultation",
            "HR Policy Consultation",
            "Answers questions about attendance, leave policies, onboarding, "
            "offboarding, and probation rules.",
            ["hr", "policy", "attendance", "leave-policy"],
            None,
        ),
        (
            "hr-benefit-consultation",
            "HR Benefits Consultation",
            "Answers questions about compensation, allowances, and employee "
            "benefits.",
            ["hr", "compensation", "benefits"],
            None,
        ),
        (
            "hr-system-operation-guide",
            "HR System Operation Guide",
            "Provides guidance for HR system operations and handbook procedures.",
            ["hr", "system", "operations"],
            None,
        ),
        (
            "hr-document-question-answering",
            "HR Document Question Answering",
            "Parses HR document links and answers questions based on document "
            "content.",
            ["hr", "document", "question-answering"],
            None,
        ),
    ]


def test_employee_data_agent_card_is_agentkit_registration_ready():
    card = build_employee_data_card(EMPLOYEE_DATA_URL)

    _assert_registration_ready(card, EMPLOYEE_DATA_URL)
    assert card.description == (
        "Provides authenticated employees with their own leave balance, medical "
        "period, and annual leave calculation. Uses stub data in this deployment."
    )
    assert [
        (skill.id, skill.name, skill.description, skill.tags, skill.examples)
        for skill in card.skills
    ] == [
        (
            "employee-leave-balance-query",
            "Employee Leave Balance Query",
            "Queries the authenticated employee's own leave balance.",
            ["hr", "employee-data", "leave-balance"],
            None,
        ),
        (
            "employee-medical-period-query",
            "Employee Medical Period Query",
            "Queries the authenticated employee's own medical period.",
            ["hr", "employee-data", "medical-period"],
            None,
        ),
        (
            "employee-annual-leave-calculation",
            "Employee Annual Leave Calculation",
            "Calculates the authenticated employee's own annual leave based on "
            "service years.",
            ["hr", "employee-data", "annual-leave"],
            None,
        ),
    ]
