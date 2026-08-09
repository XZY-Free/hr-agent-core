"""model_config：按 agent 配置模型与 thinking 档位。"""
import pytest

from apps.orchestrator.deployment.model_config import (
    DEFAULT_MODEL_NAME,
    extra_config_for,
    model_for,
)

THINKING_ENVS = ("THINKING_DEFAULT", "THINKING_ROOT", "THINKING_LEAVE",
                 "THINKING_CONSULT")
MODEL_ENVS = ("MODEL_AGENT_NAME", "MODEL_AGENT_NAME_ROOT",
              "MODEL_AGENT_NAME_LEAVE", "MODEL_AGENT_NAME_CONSULT")


@pytest.fixture
def clean_env(monkeypatch):
    """清空相关环境变量——测试不能受开发机 .env 影响（评测曾因此误 skip）。"""
    for name in THINKING_ENVS + MODEL_ENVS:
        monkeypatch.delenv(name, raising=False)


def test_thinking_defaults_to_disabled(clean_env):
    """缺省关闭 thinking：实测耗时降 79% 且质量不降（CHECKLIST E.2）。"""
    for key in ("root", "leave", "consult"):
        assert extra_config_for(key) == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }


def test_thinking_default_env_applies_to_all(clean_env, monkeypatch):
    monkeypatch.setenv("THINKING_DEFAULT", "enabled")
    for key in ("root", "leave", "consult"):
        assert extra_config_for(key)["extra_body"]["thinking"]["type"] == "enabled"


def test_per_agent_thinking_overrides_default(clean_env, monkeypatch):
    """分 agent 覆盖优先于全局——用于只给某个 agent 开回推理。"""
    monkeypatch.setenv("THINKING_DEFAULT", "disabled")
    monkeypatch.setenv("THINKING_CONSULT", "enabled")
    assert extra_config_for("consult")["extra_body"]["thinking"]["type"] == "enabled"
    assert extra_config_for("root")["extra_body"]["thinking"]["type"] == "disabled"


def test_thinking_accepts_auto_and_is_case_insensitive(clean_env, monkeypatch):
    monkeypatch.setenv("THINKING_ROOT", "  AUTO  ")
    assert extra_config_for("root")["extra_body"]["thinking"]["type"] == "auto"


def test_invalid_thinking_raises(clean_env, monkeypatch):
    """非法档位要当场报错，不能静默下发给模型。"""
    monkeypatch.setenv("THINKING_LEAVE", "fast")
    with pytest.raises(ValueError, match="THINKING_LEAVE"):
        extra_config_for("leave")


def test_model_falls_back_to_default(clean_env):
    for key in ("root", "leave", "consult"):
        assert model_for(key) == DEFAULT_MODEL_NAME


def test_global_model_env_applies_to_all(clean_env, monkeypatch):
    monkeypatch.setenv("MODEL_AGENT_NAME", "doubao-x")
    for key in ("root", "leave", "consult"):
        assert model_for(key) == "doubao-x"


def test_per_agent_model_overrides_global(clean_env, monkeypatch):
    """分 agent 换模型——留作"子 agent 用更快模型"的调优入口。"""
    monkeypatch.setenv("MODEL_AGENT_NAME", "doubao-x")
    monkeypatch.setenv("MODEL_AGENT_NAME_CONSULT", "doubao-flash")
    assert model_for("consult") == "doubao-flash"
    assert model_for("root") == "doubao-x"
