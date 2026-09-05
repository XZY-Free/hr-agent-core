"""WP-01 远端前置门禁测试专属夹具（仅作用于 tests/agentkit 目录）。

只注册 marker 并缓存「每次会话只做一次」的只读 AgentKit/HTTPS 探测结果。
不覆盖 tests/conftest.py；断言都在 test_wp01_environment.py。
"""

from __future__ import annotations

import pytest

from tests.agentkit import support
from agentkit.sdk.runtime.client import AgentkitRuntimeClient


def pytest_configure(config: "pytest.Config") -> None:
    config.addinivalue_line("markers", "agentkit: AgentKit 已部署开发 Runtime 远端验收")
    config.addinivalue_line(
        "markers",
        "wp01_remote_acceptance: WP-01 远端前置门禁（只读、真实 AgentKit 部署探测）",
    )


@pytest.fixture(scope="session")
def agentkit_client() -> AgentkitRuntimeClient:
    return support.build_agentkit_client()


@pytest.fixture(scope="session")
def service_targets() -> dict[str, support.ServiceTarget]:
    return support.load_service_targets()


@pytest.fixture(scope="session")
def probes(
    agentkit_client: AgentkitRuntimeClient,
    service_targets: dict[str, support.ServiceTarget],
) -> dict[str, support.RuntimeProbe]:
    return {
        key: support.build_probe(key=key, target=target, client=agentkit_client)
        for key, target in service_targets.items()
    }


@pytest.fixture(scope="session")
def resolve_current_version(
    agentkit_client: AgentkitRuntimeClient,
    service_targets: dict[str, support.ServiceTarget],
):
    """返回只读函数：实时取当前版本号，用于「版本前后一致」门禁。"""
    def _resolve(service: str) -> int | None:
        return support.current_version(agentkit_client, service_targets[service].runtime_id)

    return _resolve
