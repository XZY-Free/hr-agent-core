"""Verify a runtime image without printing file contents or secret values."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import PurePosixPath


_PROHIBITED_FILES = {
    "app/.env",
    "app/agentkit.yaml",
    "app/.runtime-secrets.json",
    "app/.stage1-cloud-state.json",
    "app/scripts/deploy_orchestrator.py",
    "app/scripts/test_runtime_api.py",
}
_PROHIBITED_PREFIXES = {
    "app/artifacts",
    "app/tests",
    "app/docs",
}


def is_prohibited_image_path(raw_path: str) -> bool:
    normalized = str(PurePosixPath(raw_path.lstrip("./")))
    if normalized in _PROHIBITED_FILES:
        return True
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _PROHIBITED_PREFIXES
    )


def _run(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"container command failed: operation={command[1]} exit_code={result.returncode}"
        )
    return result.stdout.strip()


def _scan_stream(stream, secrets: list[bytes]) -> bool:
    tail = b""
    overlap = max((len(secret) for secret in secrets), default=1) - 1
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            return False
        window = tail + chunk
        if any(secret in window for secret in secrets):
            return True
        tail = window[-overlap:] if overlap else b""


def verify_image(image: str, secrets: list[str]) -> dict[str, int | bool]:
    secret_bytes = [value.encode() for value in secrets if len(value) >= 8]
    prohibited_path_count = 0
    final_secret_hit_count = 0
    layer_secret_hit_count = 0
    with tempfile.TemporaryDirectory(prefix="runtime-image-gate-") as temp_dir:
        final_tar = os.path.join(temp_dir, "final.tar")
        saved_tar = os.path.join(temp_dir, "saved.tar")
        container_id = _run(["docker", "create", image])
        try:
            _run(["docker", "export", "-o", final_tar, container_id])
        finally:
            _run(["docker", "rm", "-f", container_id])

        with tarfile.open(final_tar) as archive:
            for member in archive:
                if is_prohibited_image_path(member.name):
                    prohibited_path_count += 1
                if member.isfile() and secret_bytes:
                    stream = archive.extractfile(member)
                    if stream is not None and _scan_stream(stream, secret_bytes):
                        final_secret_hit_count += 1

        _run(["docker", "image", "save", "-o", saved_tar, image])
        with tarfile.open(saved_tar) as archive:
            for member in archive:
                if not member.isfile() or not secret_bytes:
                    continue
                stream = archive.extractfile(member)
                if stream is not None and _scan_stream(stream, secret_bytes):
                    layer_secret_hit_count += 1

    return {
        "prohibited_path_count": prohibited_path_count,
        "final_secret_hit_count": final_secret_hit_count,
        "layer_secret_hit_count": layer_secret_hit_count,
        "passed": not (
            prohibited_path_count or final_secret_hit_count or layer_secret_hit_count
        ),
    }


def main() -> None:
    image = os.environ.get("RUNTIME_IMAGE", "")
    if not image:
        raise SystemExit("RUNTIME_IMAGE is required")
    raw_secrets = os.environ.get("KNOWN_SECRET_VALUES_JSON", "[]")
    secrets = json.loads(raw_secrets)
    if not isinstance(secrets, list) or not all(isinstance(item, str) for item in secrets):
        raise SystemExit("KNOWN_SECRET_VALUES_JSON must be a JSON string array")
    result = verify_image(image, secrets)
    print(json.dumps(result, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
