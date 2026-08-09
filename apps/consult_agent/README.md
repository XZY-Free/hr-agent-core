# Consult Agent应用

负责制度咨询Agent、冻结提示词、文档解析、Knowledge工具、本地Knowledge Stub和Viking官方SDK适配。`policy`、`handbook`、`salary`、`childcare`四个scope只在本应用配置和调用。

批次2由根`agent.py`把本应用构建为进程内子Agent；没有独立Runtime、AgentCard或A2A服务。
