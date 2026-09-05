"""公共交互能力声明：只声明真实测试证明的能力，不虚报。"""

# 流式传输通道（A2A SSE事件流）。
STREAMING_TRANSPORT = True
# 回答正文自身逐步增量产生（Token级）——当前未证明，不虚报。
INCREMENTAL_CONTENT = False
# 缺少业务信息时暂停等待用户补充（input-required）。
INPUT_REQUIRED = True
# input-required后客户端在同一task/context续发补充信息（真实协议与运行时均支持）。
RESUME = True
# tasks/cancel 不受支持：公共任务以官方 UnsupportedOperationError(-32004) 拒绝取消。
CANCEL = False
# 跨进程/重启后的任务持久恢复——InMemoryTaskStore，未证明。
DURABLE_TASK_RECOVERY = False

SUPPORTED_LOCALES = ("zh-CN",)


def interaction_payload() -> dict:
    return {
        "streaming_transport": STREAMING_TRANSPORT,
        "incremental_content": INCREMENTAL_CONTENT,
        "input_required": INPUT_REQUIRED,
        "resume": RESUME,
        "cancel": CANCEL,
        "durable_task_recovery": DURABLE_TASK_RECOVERY,
        "supported_locales": list(SUPPORTED_LOCALES),
    }
