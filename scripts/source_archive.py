"""Create a source archive exclusively from Git-tracked, approved paths."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


_PROHIBITED_NAMES = {
    ".runtime-secrets.json",
    ".stage1-cloud-state.json",
}
_PROHIBITED_DIRS = {
    "artifacts",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def is_allowed_archive_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path)
    parts = path.parts
    if not raw_path or path.is_absolute() or ".." in parts:
        return False
    if path.name in _PROHIBITED_NAMES:
        return False
    if path.name == ".env" or (
        path.name.startswith(".env.") and path.name != ".env.example"
    ):
        return False
    if path.name == "agentkit.yaml" or (
        path.name.startswith("agentkit") and path.suffix == ".yaml"
    ):
        return False
    if any(part in _PROHIBITED_DIRS for part in parts):
        return False
    if "tests" in parts and "logs" in parts[parts.index("tests") + 1 :]:
        return False
    if path.suffix.lower() in {".zip", ".pyc", ".pyo"}:
        return False
    return True


def build_manifest(repo_root: Path, tracked_paths: Iterable[str]) -> list[str]:
    manifest = list(tracked_paths)
    rejected = [path for path in manifest if not is_allowed_archive_path(path)]
    if rejected:
        raise ValueError(f"prohibited archive path count: {len(rejected)}")
    missing = [path for path in manifest if not (repo_root / path).is_file()]
    if missing:
        raise ValueError(f"missing tracked file count: {len(missing)}")
    return manifest


def tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def create_archive(repo_root: Path, output: Path) -> tuple[int, str]:
    manifest = build_manifest(repo_root, tracked_paths(repo_root))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in manifest:
            archive.write(repo_root / relative_path, relative_path)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return len(manifest), digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    count, digest = create_archive(args.repo.resolve(), args.output.resolve())
    print({"file_count": count, "sha256": digest})


if __name__ == "__main__":
    main()
