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

**缺省为 disabled**，依据 2026-07-30 的对照实验（CHECKLIST E.2）：全关 thinking
连跑两轮 22/22、耗时 138.9s/139.8s，对比全开的 22/22、656.8s——耗时降 79%，
通过率不变，稳定性反而更好（全开时每轮都有 1~2 条 case 随机掉红）。回答质量
逐条比对轨迹后确认不降反升。需要推理时显式设 enabled 即可。
"""
import os

DEFAULT_MODEL_NAME = "doubao-seed-1.6-250615"
DEFAULT_THINKING = "disabled"
VALID_THINKING = ("enabled", "disabled", "auto")


def model_for(agent_key: str) -> str:
    """取该 agent 的模型名：MODEL_AGENT_NAME_<KEY> > MODEL_AGENT_NAME > 缺省。"""
    default = os.getenv("MODEL_AGENT_NAME", DEFAULT_MODEL_NAME)
    return os.getenv(f"MODEL_AGENT_NAME_{agent_key.upper()}", default)


def extra_config_for(agent_key: str) -> dict:
    """取该 agent 的 model_extra_config（目前只含 thinking 档位）。

    veADK 会把这里的 extra_body 合并进 DEFAULT_MODEL_EXTRA_CONFIG
    （见 veadk/agent.py 的 model_extra_config 构造），故只需给出要覆盖的键。
    """
    mode = (os.getenv(f"THINKING_{agent_key.upper()}")
            or os.getenv("THINKING_DEFAULT")
            or DEFAULT_THINKING)
    mode = mode.strip().lower()
    if mode not in VALID_THINKING:
        raise ValueError(
            f"THINKING_{agent_key.upper()} 取值非法：{mode!r}，可选 {VALID_THINKING}"
        )
    return {"extra_body": {"thinking": {"type": mode}}}
