"""单镜像多Runtime的不可混淆启动入口。"""

from pathlib import Path

import pytest

from deployment.runtime_entry import runtime_module


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("runtime_app", "module"),
    [
        ("orchestrator", "agent"),
        ("consult", "apps.consult_agent.cloud"),
        ("employee-data", "apps.employee_data_agent.cloud"),
    ],
)
def test_runtime_app_maps_to_one_explicit_module(runtime_app, module):
    assert runtime_module(runtime_app) == module


def test_runtime_app_fails_closed_when_missing_or_unknown():
    with pytest.raises(RuntimeError, match="HR_RUNTIME_APP"):
        runtime_module("")
    with pytest.raises(RuntimeError, match="HR_RUNTIME_APP"):
        runtime_module("consult-local")


def test_runtime_dockerfile_uses_dispatcher_and_runtime_port():
    dockerfile = (REPO_ROOT / "deployment" / "Dockerfile.runtime").read_text()

    assert "EXPOSE 8000" in dockerfile
    assert 'CMD ["python", "-m", "deployment.runtime_entry"]' in dockerfile


def test_runtime_dockerfile_copies_only_allowlisted_runtime_inputs():
    dockerfile = (REPO_ROOT / "deployment" / "Dockerfile.runtime").read_text()
    copy_lines = [
        line.split("#", 1)[0].strip()
        for line in dockerfile.splitlines()
        if line.split("#", 1)[0].strip().upper().startswith("COPY ")
    ]

    assert not any(line in {"COPY . .", "COPY . /app", "COPY ./ /app"} for line in copy_lines)
    assert copy_lines == [
        "COPY requirements.txt /app/requirements.txt",
        "COPY agent.py /app/agent.py",
        "COPY apps/ /app/apps/",
        "COPY packages/ /app/packages/",
        "COPY deployment/ /app/deployment/",
    ]


def test_dockerignore_excludes_sensitive_and_nonruntime_paths():
    patterns = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".env",
        ".env.*",
        "agentkit.yaml",
        "agentkit*.yaml",
        ".runtime-secrets.json",
        ".stage1-cloud-state.json",
        "artifacts/",
        "scripts/",
        "tests/",
        "docs/",
        ".pytest_cache/",
        "**/__pycache__/",
        "*.log",
        "*.zip",
    } <= patterns
