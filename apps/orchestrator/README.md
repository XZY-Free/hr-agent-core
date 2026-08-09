# Orchestrator应用

负责当前根Agent、一级意图分流、页面跳转、JUMP回调和本地请假Agent装配接口。它通过构建函数接收咨询Agent、请假Agent和员工数据工具，不导入其他应用的Agent实例。

批次2仍由仓库根`agent.py`完成单Runtime依赖注入。本目录不包含Knowledge、文档解析、Gaia HTTP客户端或A2A客户端。
