"""测试夹具：为结构测试提供占位模型 Key，避免 Agent 实例化时触发 veADK veauth 联网取 token。

- 结构/规则/工具单测不调真实模型，占位 Key 足够。
- 评测测试（@pytest.mark.eval）需要真实方舟 Key：在 .env 设置 MODEL_AGENT_API_KEY，
  setdefault 不会覆盖已设值。
- 生产运行（agent.py）不走 conftest，由 .env 提供真实 Key。
"""
import os

os.environ.setdefault("MODEL_AGENT_API_KEY", "dummy-for-struct-test-only")
