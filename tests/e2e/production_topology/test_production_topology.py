"""生产拓扑业务验收（WP-07，stub E2E，不依赖 local_agent.py）。

用真实 production builder 装配，验证：
- 拓扑结构（真实 build_agent_application / Consult / Employee Data 正式 builder）；
- Public A2A → HrAssistantRuntime → Semantic Router → 目标 Agent 的路由正确；
- 各类失败（identity / semantic router / attachment / A2A 不可用）不 silent fallback；
- 关键 Golden Matrix 由 L1/L2 确定性测试承接（本套件在 stub 拓扑下复核路由与装配）。

真实模型/Viking/Gaia 业务链属 L5 opt-in，见 README。
"""

import os
import pytest

from apps.orchestrator.a2a.router import OrchestratorRemoteRouter
from apps.orchestrator.a2a.routing import DeterministicRouteTable, RouteTarget
from apps.orchestrator.public_runtime.attachments import AttachmentResolutionError

# 生产装配无真实模型 key 时也能构建拓扑（仅构造，不触发调用）。
DUMMY_KEY = "dummy-for-struct-test-only"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.production_topology,
]


def _payload(text, *, user_id="user-a", session_id="session-a", task_id=None):
    payload = {
        "user_id": user_id,
        "session_id": session_id,
        "new_message": {"parts": [{"text": text}]},
    }
    if task_id:
        payload["task_id"] = task_id
    return payload


class _DownstreamUnavailableClient:
    """模拟 A2A 下游不可用：路由 target 正确但失败，不 silent fallback。"""

    async def invoke(self, *, base_url, request, spec):
        from packages.agent_runtime.a2a.client import A2AInvocationError
        raise A2AInvocationError("a2a_unavailable")


@pytest.fixture(scope="module")
def application():
    from agent import build_agent_application
    os.environ.setdefault("MODEL_AGENT_API_KEY", DUMMY_KEY)
    return build_agent_application()


def test_production_topology_builds_via_real_builders(application):
    """真实 builder 装配出 Leave 本地 + 远程 Consult/Employee Data 的生产拓扑。"""
    app = application
    assert app.leave_agent.name == "leave_agent"
    assert app.root_agent.name == "root_agent"
    # 生产拓扑不含"本地 consult/employee 子 Agent"——它们由 A2A 远程承担。
    names = {a.name for a in app.root_agent.sub_agents}
    assert "leave_agent" in names
    assert not {"hr_consult_agent", "hr_employee_data_agent"} & names


def test_consult_and_employee_runtime_builders_are_real():
    """Consult / Employee Data 使用正式 runtime builder + stub provider。

    不 import local_agent.py；不复制"看起来一样"的 test root。
    """
    import apps.consult_agent.runtime as consult_rt
    import apps.employee_data_agent.runtime as emp_rt

    assert callable(consult_rt.build_consult_runtime)
    assert callable(emp_rt.build_employee_data_runtime)
    consult = consult_rt.build_consult_runtime(validate_config=False)
    assert consult is not None
    assert hasattr(consult, "run")


# ---------- 路由 Golden（真实 route_table，无 LLM） ----------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我想休年假", RouteTarget.LOCAL),
        ("明天请一天年假", RouteTarget.LOCAL),
        ("我还有几天年假", RouteTarget.EMPLOYEE_DATA),
        ("我的育儿假剩几天", RouteTarget.EMPLOYEE_DATA),
        ("年假能跨年吗", RouteTarget.CONSULT),
        ("四川育儿假有几天", RouteTarget.CONSULT),
        ("迟到17分钟扣多少", RouteTarget.CONSULT),
        ("育儿假", RouteTarget.LOCAL),         # 无上下文 → needs_clarification → local
    ],
)
def test_semantic_golden_routes(text, expected):
    table = DeterministicRouteTable()
    assert table.decide(text, user_id="user-a", session_id="session-a") == expected


def test_three_anchor_sentences_route_correctly(application):
    """§8 三条锚点句分别应路由 Leave / Employee Data / Consult。"""
    table = application.remote_router.route_table
    assert table.decide("我想休年假", user_id="u", session_id="s") == RouteTarget.LOCAL
    assert table.decide("我年假还有多少", user_id="u", session_id="s") == RouteTarget.EMPLOYEE_DATA
    assert table.decide("年假能跨年吗", user_id="u", session_id="s") == RouteTarget.CONSULT


# ---------- 路由失败不 silent fallback ----------

@pytest.mark.parametrize(
    ("text", "expected_target"),
    [
        ("我还有几天年假", "hr-employee-data-agent"),
        ("迟到扣款制度是什么", "hr-consult-agent"),
    ],
)
def test_remote_downstream_unavailable_never_falls_back_to_other_target(
    text, expected_target
):
    """A2A 下游不可用：target 仍按语义路由正确，失败显式，不回落到另一业务域或本地 consult。"""
    import asyncio

    router = OrchestratorRemoteRouter(
        client=_DownstreamUnavailableClient(),
        route_table=DeterministicRouteTable(),
    )
    response = asyncio.run(router.route(_payload(text)))
    assert response.target == expected_target
    assert response.status == "failed"
    assert response.error_code == "a2a_unavailable"


# ---------- Fail injection：semantic router 失败不 silent fallback ----------

def test_semantic_router_failure_never_defaults_to_consult():
    """语义路由器异常 → 安全兜底 local/needs_clarification，绝不 silent remote dispatch。"""
    from apps.orchestrator.a2a.semantic_router import (
        Confidence,
        SemanticRouter,
        safe_decision,
    )

    def _boom(text, state):
        raise RuntimeError("semantic router down")

    router = SemanticRouter(classifier=_boom)
    decision = router.classify("帮我查一下制度", {})
    assert decision.target.value == "local"
    assert decision.confidence is Confidence.LOW


def test_identity_resolution_failure_does_not_fallback_to_user_id():
    """identity 未映射 → identity_unverified，绝不把 user_id 当 employee_id。"""
    from apps.orchestrator.public_runtime.attachments import AttachmentResolver  # noqa: F401
    from packages.hr_domain.execution.context import (
        HREXecutionContext,
        bind_hr_execution_context,
        require_employee_identity,
    )
    from packages.hr_domain.gaia.config import GaiaServerConfig
    from packages.hr_domain.gaia.provider import GaiaProvider
    from packages.hr_domain.identity import IdentityResolutionError, TrustedIdentityResolver

    config = GaiaServerConfig(corp_id="c", client_secret="s", grant_type="g",
                              schedule_tenant="t")
    ctx = HREXecutionContext(
        internal_user_id="unknown-user",
        identity_resolver=TrustedIdentityResolver({"known": "EMP-001"}, ref_secret="sec"),
        gaia_config=config,
        gaia_provider=GaiaProvider(config),
        request_id="r", context_id="c",
    )
    with bind_hr_execution_context(ctx):
        try:
            require_employee_identity()
            assert False
        except IdentityResolutionError as exc:
            assert exc.error_code == "identity_unverified"


# ---------- Attachment fail-closed（生产边界） ----------

def test_attachment_fails_closed_not_silently_ignored():
    from apps.orchestrator.public_runtime.attachments import AttachmentResolver

    refs = [type("R", (), {
        "reference_id": "ref-1", "resource_type": "snowharness_file",
        "display_name": "x.pdf", "media_type": "application/pdf"})()]
    resolver = AttachmentResolver()
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all(refs)
    # fail-closed：不静默忽略 / 不假装已读取；类型不受支持或无 resolver 均属明确失败。
    assert exc.value.error_code in {"attachment_type_not_supported", "attachment_not_resolvable"}
