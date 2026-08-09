"""Viking 真实知识库回归；必须显式开启，不以 Stub 代替。"""
import os
from numbers import Real

import pytest

from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend


RUN_REAL = os.getenv("RUN_REAL_KNOWLEDGE_TESTS") == "true"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_REAL,
        reason="未设置 RUN_REAL_KNOWLEDGE_TESTS=true，真实 Viking 回归未执行",
    ),
]


@pytest.mark.parametrize(
    ("scope", "query"),
    [
        ("policy", "迟到扣款规定"),
        ("handbook", "销假申请操作流程"),
        ("salary", "膳食福利标准"),
        ("childcare", "四川省育儿假"),
    ],
)
def test_real_viking_preserves_content_source_score(scope, query):
    results = AgentKitKnowledgeBackend().search(query, scope=scope, top_k=5)

    assert results
    for item in results:
        assert isinstance(item["content"], str) and item["content"]
        assert isinstance(item["source"], str) and item["source"]
        assert isinstance(item["score"], Real) and not isinstance(item["score"], bool)


def test_real_viking_keeps_low_score_observable_without_threshold():
    results = AgentKitKnowledgeBackend().search(
        "年假能跨年用吗", scope="policy", top_k=5
    )

    assert results
    assert all(item["source"] for item in results)
    assert all(isinstance(item["score"], Real) for item in results)
