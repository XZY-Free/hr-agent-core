"""顶层统一结果合同与稳定错误码。"""

# 公共结果稳定字段。
RESULT_FIELDS = (
    "request_id",
    "status",
    "answer",
    "result_type",
    "data",
    "actions",
    "error_code",
    "retryable",
    "agent_name",
    "agent_version",
)

# 统一错误语义（用户展示文本与机器错误分离）。
ERROR_CODES = (
    "identity_required",
    "identity_unverified",
    "input_required",
    "not_found",
    "rejected",
    "temporarily_unavailable",
    "failed",
    "cancelled",
    "contract_error",
)


def result_contract_payload() -> dict:
    return {
        "fields": list(RESULT_FIELDS),
        "error_codes": list(ERROR_CODES),
        "notes": {
            "zh-CN": (
                "answer为人类可读主回答；result_type为结果类别；data为可选结构化"
                "数据；actions为可选宿主可执行动作（第一版无通用动作协议时为空）；"
                "error_code为稳定机器错误；retryable表示是否适合重试。"
            ),
        },
    }
