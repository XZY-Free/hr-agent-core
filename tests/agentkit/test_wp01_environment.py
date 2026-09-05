"""WP-01 远端前置门禁：AgentKit 已部署开发 Runtime 是测试唯一目标。

只做「前置门禁」：证明三个开发 Runtime 达到被验收所需的环境就绪度。
不覆盖 WP-01 完整业务；只验证用户当前授权模式（本地 Gaia 保持 stub）。

- 证据只来自 AgentKit read API 与三个真实 HTTPS endpoint；
- 旧入口 root_agent / 缺共享 identity map/ref / 部署镜像不对应待验收版本 仍明确 FAIL；
- 无 skip / xfail / 自动成功；本文件不改任何生产代码。
"""

from __future__ import annotations

import pytest

from tests.agentkit import support

SERVICES = ["orchestrator", "consult", "employee_data"]
MARK = pytest.mark.agentkit


# ---------- 三服务共用只读门禁 ----------


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_sdk_discovery_not_blocked(probes, service):
    """AgentKit 读可完成，无环境级阻塞（接口失败/版本缺失/发布镜像缺失/端点缺失）。"""
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    assert probe.current_version is not None, f"{service} 未取到当前版本号"


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_deployment_status_ready(probes, service):
    """当前与已发布版本都必须处于 Ready 部署态，且发布版本号等于所选当前版本号。"""
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    assert probe.current_status == "Ready", f"{service} 当前状态={probe.current_status}"
    assert probe.published_status == "Ready", f"{service} 发布状态={probe.published_status}"
    assert probe.published_version == probe.current_version, (
        f"{service} 发布版本={probe.published_version} != 当前版本={probe.current_version}"
    )


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_runtime_endpoint_is_public_https(probes, service):
    """endpoint 必须是公网 HTTPS，无 credential/query/fragment/私有网段/奇怪host。"""
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    assert probe.endpoint_issue is None, f"{service} 端点不合规: {probe.endpoint_issue}"


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_runtime_health_is_200(probes, service):
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    assert probe.endpoint_issue is None, f"{service} 端点不合规: {probe.endpoint_issue}"
    assert probe.api_key_configured, f"{service} 未配置 acceptance key: {probe.api_key_env}"
    assert probe.health_status == 200, (
        f"{service} 健康检查非200: status={probe.health_status} error={probe.health_error}"
    )


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_runtime_card_identity(probes, service):
    """公共卡名称/版本/协议版本必须与待验收一致（旧入口 root_agent 在此失败）。"""
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    assert probe.endpoint_issue is None, f"{service} 端点不合规: {probe.endpoint_issue}"
    assert probe.api_key_configured, f"{service} 未配置 acceptance key: {probe.api_key_env}"
    assert probe.card_status == 200, (
        f"{service} AgentCard 获取失败: status={probe.card_status} error={probe.card_error}"
    )
    assert probe.card_name == probe.expected_card_name, (
        f"{service} AgentCard 名称不一致: 期望 {probe.expected_card_name}"
    )
    assert probe.card_version == support.PUBLIC_CARD_VERSION, (
        f"{service} card 版本={probe.card_version} 期望 {support.PUBLIC_CARD_VERSION}"
    )
    assert probe.card_protocol_version == support.CARD_PROTOCOL_VERSION, (
        f"{service} protocol_version={probe.card_protocol_version} "
        f"期望 {support.CARD_PROTOCOL_VERSION}"
    )


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_runtime_advertised_url_matches_endpoint(probes, service):
    """AgentCard 公布 url 必须与该 Runtime 实际 endpoint 一致，避免向未知主机发请求。"""
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    assert probe.endpoint_issue is None, f"{service} 端点不合规: {probe.endpoint_issue}"
    assert probe.api_key_configured, f"{service} 未配置 acceptance key: {probe.api_key_env}"
    assert probe.card_url_issue is None, f"{service} 公布 url 不合规: {probe.card_url_issue}"
    assert probe.advertised_url_matches is True, f"{service} 公布 url 与实际 endpoint 不一致"


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_runtime_version_is_stable(resolve_current_version, probes, service):
    """探测前后当前版本一致，避免版本切换导致「假通过」。"""
    probe = probes[service]
    assert probe.blocker is None, f"{service} 被阻塞: {probe.blocker}"
    after = resolve_current_version(service)
    assert after == probe.current_version, (
        f"{service} 版本在探测期间发生变化: before={probe.current_version} after={after}"
    )


@MARK
@pytest.mark.parametrize("service", SERVICES)
def test_image_bound_to_expected_artifact(probes, service):
    """部署镜像必须与该服务操作员显式指定的待验收不可变镜像一致；映射未配置/非法则本 gate 明确失败。

    每个服务只与自身显式 expected 镜像比较，绝不回退到单一镜像或运行时发现状态。
    """
    probe = probes[service]
    expected = support.load_expected_images()[service]
    assert probe.artifact_url, f"{service} 未取到已发布镜像"
    assert probe.artifact_url == expected, f"{service} 运行时镜像与待验收镜像不对应"


# ---------- 分服务后端/身份/集合配置门禁（当前授权模式下） ----------


@MARK
def test_orchestrator_authorized_gaia_stub_and_identity(probes):
    """Orchestrator 授权模式：GAIA_BACKEND=stub + dry-run=true + GAIA_STUB_JSON 存在 + 共享身份 map/ref。"""
    probe = probes["orchestrator"]
    assert probe.blocker is None, f"orchestrator 被阻塞: {probe.blocker}"
    assert probe.backends.get(support.GAIA_BACKEND_KEY) == "stub", (
        f"orchestrator GAIA_BACKEND={probe.backends.get(support.GAIA_BACKEND_KEY)} 期望 stub"
    )
    assert probe.flags.get(support.GAIA_DRY_RUN_KEY) == "true", (
        f"orchestrator GAIA_DRY_RUN={probe.flags.get(support.GAIA_DRY_RUN_KEY)} 期望 true"
    )
    assert probe.present.get(support.GAIA_STUB_JSON_KEY), "orchestrator 缺失 GAIA_STUB_JSON"
    missing_identity = [k for k in support.IDENTITY_KEYS if not probe.present.get(k)]
    assert not missing_identity, f"orchestrator 缺失共享身份 map/ref: {','.join(missing_identity)}"


@MARK
def test_employee_data_authorized_stub_and_identity(probes):
    """Employee Data 授权模式：EMPLOYEE_DATA_BACKEND=stub + EMPLOYEE_DATA_STUB_JSON 存在 + 共享身份 map/ref。"""
    probe = probes["employee_data"]
    assert probe.blocker is None, f"employee_data 被阻塞: {probe.blocker}"
    assert probe.backends.get(support.EMPLOYEE_DATA_BACKEND_KEY) == "stub", (
        f"employee_data EMPLOYEE_DATA_BACKEND="
        f"{probe.backends.get(support.EMPLOYEE_DATA_BACKEND_KEY)} 期望 stub"
    )
    assert probe.present.get(support.EMPLOYEE_DATA_STUB_JSON_KEY), "employee_data 缺失 EMPLOYEE_DATA_STUB_JSON"
    missing_identity = [k for k in support.IDENTITY_KEYS if not probe.present.get(k)]
    assert not missing_identity, f"employee_data 缺失共享身份 map/ref: {','.join(missing_identity)}"


@MARK
def test_consult_agentkit_and_collections(probes):
    """Consult：KB_BACKEND=agentkit，且四个 collection 配置具备。"""
    probe = probes["consult"]
    assert probe.blocker is None, f"consult 被阻塞: {probe.blocker}"
    assert probe.backends.get(support.KB_BACKEND_KEY) == "agentkit", (
        f"consult KB_BACKEND={probe.backends.get(support.KB_BACKEND_KEY)} 期望 agentkit"
    )
    missing = [k for k in support.CONSULT_COLLECTION_KEYS if not probe.present.get(k)]
    assert not missing, f"consult 缺失 Knowledge collection 配置: {','.join(missing)}"
