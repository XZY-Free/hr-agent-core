from pathlib import Path

import pytest

from scripts.source_archive import build_manifest, is_allowed_archive_path


def test_archive_path_gate_rejects_local_and_sensitive_files():
    rejected = [
        ".env",
        ".env.local",
        "agentkit.yaml",
        "agentkit-dev.yaml",
        ".runtime-secrets.json",
        ".stage1-cloud-state.json",
        "artifacts/planner/task.md",
        "tests/eval/logs/result.jsonl",
        "pkg/__pycache__/module.pyc",
        ".pytest_cache/state",
        "bundle.zip",
    ]

    assert all(not is_allowed_archive_path(path) for path in rejected)
    assert is_allowed_archive_path(".env.example")
    assert is_allowed_archive_path("agent.py")
    assert is_allowed_archive_path("docs/README.md")


def test_archive_manifest_allows_tracked_env_example_but_rejects_real_env(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in (".env.example", ".env"):
        (repo / name).write_text("NAME=example")

    assert build_manifest(repo, [".env.example"]) == [".env.example"]
    with pytest.raises(ValueError, match="prohibited archive path"):
        build_manifest(repo, [".env"])


def test_archive_manifest_rejects_any_prohibited_tracked_path(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = ["agent.py", "docs/README.md", "tests/eval/logs/result.jsonl"]
    for name in tracked:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")

    with pytest.raises(ValueError, match="prohibited archive path"):
        build_manifest(repo, tracked)


def test_archive_manifest_keeps_tracked_allowed_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = ["agent.py", "docs/README.md"]
    for name in tracked:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")

    assert build_manifest(repo, tracked) == tracked
