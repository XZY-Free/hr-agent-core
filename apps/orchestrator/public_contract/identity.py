"""公共智能体身份：SnowHarness 唯一可见的顶层稳定标识。"""

PUBLIC_AGENT_ID = "hr-assistant"
PUBLIC_AGENT_NAME_ZH = "企业人力智能助手"
PUBLIC_AGENT_NAME_EN = "Enterprise HR Assistant"
PUBLIC_AGENT_VERSION = "1.0.0"

PUBLIC_PROVIDER_ORGANIZATION = "HR Agent Team"

# 禁止在公共合同中出现的内部拓扑/实现词，供泄露检查使用。
FORBIDDEN_INTERNAL_TERMS = (
    "root_agent",
    "hr_orchestrator",
    "leave_agent",
    "hr-consult-agent",
    "hr-employee-data-agent",
    "veadk",
    "veADK",
    "AgentKit",
    "agentkit",
    "Gaia",
    "gaia",
    "DeterministicA2AMiddleware",
    "OrchestratorRemoteRouter",
    "employee_id",
    "corp_id",
    "client_secret",
    "runtime_api_key",
    "api_key",
    "Authorization",
    "Bearer",
)
