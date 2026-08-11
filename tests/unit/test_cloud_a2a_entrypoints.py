"""独立A2A应用的本地与云端入口门禁。"""

from typing import Any

import httpx
import pytest
import uvicorn
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import AgentCard

from apps.consult_agent.a2a import server as consult_server
from apps.consult_agent.a2a.card import build_agent_card as build_consult_card
from apps.employee_data_agent.a2a import server as employee_server
from apps.employee_data_agent.a2a.card import build_agent_card as build_employee_card


def _assert_ascii_leaf_strings(value: Any) -> None:
    if isinstance(value, str):
        assert all(0x20 <= ord(character) <= 0x7E for character in value)
    elif isinstance(value, dict):
        for key, child in value.items():
            _assert_ascii_leaf_strings(key)
            _assert_ascii_leaf_strings(child)
    elif isinstance(value, list):
        for child in value:
            _assert_ascii_leaf_strings(child)


def _assert_resolved_cloud_card(card: AgentCard, expected_url: str) -> None:
    payload = card.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert AgentCard.model_validate(payload) == card
    _assert_ascii_leaf_strings(payload)
    assert len({skill.id for skill in card.skills}) == len(card.skills)
    schemes = set((payload.get("securitySchemes") or {}).keys())
    assert all(
        set(requirement).issubset(schemes)
        for requirement in payload.get("security") or []
    )
    assert card.url == expected_url
    assert card.url.startswith("https://")
    assert not any(
        blocked in card.model_dump_json(by_alias=True, exclude_none=True)
        for blocked in (
            "127.0.0.1",
            "localhost",
            "8101",
            "8102",
            "test-runtime-api-key",
        )
    )


def test_consult_agent_card_uses_configured_cloud_url(monkeypatch):
    monkeypatch.setenv(
        "HR_CONSULT_A2A_BASE_URL",
        "https://consult.example.invalid/runtime",
    )

    card = build_consult_card()

    assert card.url == "https://consult.example.invalid/runtime/"
    assert card.provider.url == "https://consult.example.invalid/runtime"


def test_employee_agent_card_uses_configured_cloud_url(monkeypatch):
    monkeypatch.setenv(
        "HR_EMPLOYEE_DATA_A2A_BASE_URL",
        "https://employee.example.invalid/runtime",
    )

    card = build_employee_card()

    assert card.url == "https://employee.example.invalid/runtime/"
    assert card.provider.url == "https://employee.example.invalid/runtime"


def test_local_agent_card_defaults_remain_unchanged(monkeypatch):
    monkeypatch.delenv("HR_CONSULT_A2A_BASE_URL", raising=False)
    monkeypatch.delenv("HR_EMPLOYEE_DATA_A2A_BASE_URL", raising=False)

    assert build_consult_card().url == "http://127.0.0.1:8101/"
    assert build_employee_card().url == "http://127.0.0.1:8102/"


def test_consult_cloud_entry_listens_on_runtime_port(monkeypatch):
    calls = []
    monkeypatch.setattr(consult_server, "build_a2a_app", lambda: "consult-app")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    consult_server.run_cloud_server()

    assert calls == [(('consult-app',), {"host": "0.0.0.0", "port": 8000})]


def test_employee_cloud_entry_listens_on_runtime_port(monkeypatch):
    calls = []
    monkeypatch.setattr(employee_server, "build_a2a_app", lambda: "employee-app")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    employee_server.run_cloud_server()

    assert calls == [(('employee-app',), {"host": "0.0.0.0", "port": 8000})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment_name", "cloud_url", "app_builder", "expected_skills"),
    [
        (
            "HR_CONSULT_A2A_BASE_URL",
            "https://consult.example.invalid",
            consult_server.build_a2a_app,
            4,
        ),
        (
            "HR_EMPLOYEE_DATA_A2A_BASE_URL",
            "https://employee.example.invalid",
            employee_server.build_a2a_app,
            3,
        ),
    ],
)
async def test_official_resolver_reads_registration_ready_cloud_card(
    monkeypatch,
    environment_name,
    cloud_url,
    app_builder,
    expected_skills,
):
    monkeypatch.setenv(environment_name, cloud_url)
    app = app_builder(runtime=object())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=cloud_url,
    ) as http:
        card = await A2ACardResolver(http, cloud_url).get_agent_card()

    _assert_resolved_cloud_card(card, f"{cloud_url}/")
    assert len(card.skills) == expected_skills
