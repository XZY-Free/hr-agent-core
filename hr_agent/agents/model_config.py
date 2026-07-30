"""按 agent 分别配置模型与 thinking 档位。

背景：延迟实测（docs/CHECKLIST.md E）单轮中位 26.8s，主要开销是
doubao-seed-1.6 在每一跳（root 判断 → transfer → 子 agent 判断 → 组织回答）
都产生数百到近 1800 字的 thinking。但三个 agent 的任务难度并不相同：
  root_agent    —— 7 条规则的意图分类，规则明确
  leave_agent   —— 槽位补齐、多轮状态跟踪、校验失败转述
  consult_agent —— 口语改写、scope 选择，并从检索结果里筛出相关内容
                   （实测 top1 常不相关、score 普遍 0.2~0.3，最吃理解力）
故做成可分别配置，用 22 条评测集做质量/延迟的对照实验，靠数据决定各自档位，
而不是一刀切。

环境变量（均可缺省）：
  MODEL_AGENT_NAME              全局模型，缺省 doubao-seed-1.6-250615
  MODEL_AGENT_NAME_<KEY>        覆盖单个 agent 的模型，KEY ∈ ROOT/LEAVE/CONSULT
  THINKING_DEFAULT              全局 thinking 档位：enabled/disabled/auto
  THINKING_<KEY>                覆盖单个 agent 的 thinking 档位
不设置时不下发 thinking 参数，即跟随模型默认行为（doubao-seed-1.6 默认思考）。
"""
import os

DEFAULT_MODEL_NAME = "doubao-seed-1.6-250615"
VALID_THINKING = ("enabled", "disabled", "auto")


def model_for(agent_key: str) -> str:
    """取该 agent 的模型名：MODEL_AGENT_NAME_<KEY> > MODEL_AGENT_NAME > 缺省。"""
    default = os.getenv("MODEL_AGENT_NAME", DEFAULT_MODEL_NAME)
    return os.getenv(f"MODEL_AGENT_NAME_{agent_key.upper()}", default)


def extra_config_for(agent_key: str) -> dict:
    """取该 agent 的 model_extra_config（目前只含 thinking 档位）。

    返回空 dict 表示不下发 thinking 参数。veADK 会把这里的 extra_body 合并进
    DEFAULT_MODEL_EXTRA_CONFIG（见 veadk/agent.py 的 _build_model_extra_config），
    故只需给出要覆盖的键。
    """
    mode = os.getenv(f"THINKING_{agent_key.upper()}") or os.getenv("THINKING_DEFAULT")
    if not mode:
        return {}
    mode = mode.strip().lower()
    if mode not in VALID_THINKING:
        raise ValueError(
            f"THINKING_{agent_key.upper()} 取值非法：{mode!r}，可选 {VALID_THINKING}"
        )
    return {"extra_body": {"thinking": {"type": mode}}}
