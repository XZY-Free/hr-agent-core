"""测试夹具：为结构测试提供占位模型 Key，避免 Agent 实例化时触发 veADK veauth 联网取 token。

- 结构/规则/工具单测不调真实模型，占位 Key 足够。
- 评测测试（@pytest.mark.eval）需要真实方舟 Key：在 .env 设置 MODEL_AGENT_API_KEY，
  setdefault 不会覆盖已设值。
- 生产运行（agent.py）不走 conftest，由 .env 提供真实 Key。
"""
import os
from pathlib import Path

# veADK 默认 DEBUG 会打印完整工具响应；评测证据另行记录脱敏后的调用轨迹。
os.environ.setdefault("LOGGING_LEVEL", "INFO")

# pytest 默认不加载 .env，需在此主动加载，否则真实 Key 在 conftest 执行时尚未入环境，
# 下方 setdefault 会把 dummy 设进去导致评测永远 skip。
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

os.environ.setdefault("MODEL_AGENT_API_KEY", "dummy-for-struct-test-only")
