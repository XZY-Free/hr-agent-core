"""生产拓扑验收测试包（WP-07）。

使用真实 production builder（build_agent_application / build_runtime / Consult /
Employee Data 正式 runtime builder）装配，stub provider + deterministic semantic
router fixture；不依赖 local_agent.py 模拟生产，不复制另一套业务代码。
"""
