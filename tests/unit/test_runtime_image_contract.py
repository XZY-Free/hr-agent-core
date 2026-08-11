from scripts.verify_runtime_image import is_prohibited_image_path


def test_runtime_image_gate_rejects_nonruntime_and_sensitive_paths():
    prohibited = [
        "app/.env",
        "app/agentkit.yaml",
        "app/.runtime-secrets.json",
        "app/.stage1-cloud-state.json",
        "app/scripts/deploy_orchestrator.py",
        "app/scripts/test_runtime_api.py",
        "app/artifacts/planner/task.md",
        "app/tests/unit/test_runtime_entry.py",
        "app/docs/README.md",
    ]

    assert all(is_prohibited_image_path(path) for path in prohibited)
    assert not is_prohibited_image_path("app/agent.py")
    assert not is_prohibited_image_path("app/apps/consult_agent/cloud.py")
    assert not is_prohibited_image_path("app/packages/agent_runtime/a2a/client.py")
    assert not is_prohibited_image_path("app/deployment/runtime_entry.py")
