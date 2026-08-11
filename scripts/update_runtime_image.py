"""Update one existing Runtime to a pre-pushed image without changing configuration."""

from __future__ import annotations

import hashlib
import json
import os
import time

import httpx
from agentkit.sdk.runtime.client import AgentkitRuntimeClient
from agentkit.sdk.runtime.types import (
    EnvsItemForUpdateRuntime,
    GetRuntimeRequest,
    GetRuntimeVersionRequest,
    UpdateRuntimeRequest,
)


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _stable_digest(value) -> str:
    def jsonable(item):
        if hasattr(item, "model_dump"):
            return jsonable(item.model_dump(by_alias=True, exclude_none=True))
        if isinstance(item, dict):
            return {key: jsonable(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [jsonable(nested) for nested in item]
        return item

    encoded = json.dumps(
        jsonable(value), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _protected_configuration(runtime) -> dict[str, object]:
    return {
        "name": runtime.name,
        "cpu_milli": runtime.cpu_milli,
        "memory_mb": runtime.memory_mb,
        "min_instance": runtime.min_instance,
        "max_instance": runtime.max_instance,
        "max_concurrency": runtime.max_concurrency,
        "project_name": runtime.project_name,
        "apmplus_enable": runtime.apmplus_enable,
        "role_name": runtime.role_name,
        "model_agent_name": runtime.model_agent_name,
        "knowledge_id": runtime.knowledge_id,
        "memory_id": runtime.memory_id,
        "mcp_toolset_id": runtime.mcp_toolset_id,
        "tool_id": runtime.tool_id,
        "authorizer_digest": _stable_digest(runtime.authorizer_configuration),
        "network_digest": _stable_digest(runtime.network_configurations),
        "tls_digest": _stable_digest(runtime.tls_configuration),
        "env_digest": _stable_digest(sorted(
            runtime.envs or [], key=lambda item: (item.key, item.value or "")
        )),
    }


def _env_map(envs) -> dict[str, str | None]:
    return {item.key: item.value for item in envs or []}


def _apply_env_patch(envs, patch: dict[str, str]) -> list[EnvsItemForUpdateRuntime]:
    values = _env_map(envs)
    values.update(patch)
    return [
        EnvsItemForUpdateRuntime(key=key, value=value)
        for key, value in sorted(values.items())
    ]


def _verify_env_patch(before, after, patch: dict[str, str]) -> bool:
    expected = _env_map(before)
    expected.update(patch)
    return _env_map(after) == expected


def main() -> None:
    runtime_id = _required("RUNTIME_ID")
    image = _required("RUNTIME_IMAGE")
    api_key = _required("RUNTIME_API_KEY")
    try:
        env_patch = json.loads(os.environ.get("RUNTIME_ENV_PATCH_JSON", "{}"))
    except json.JSONDecodeError:
        raise SystemExit("RUNTIME_ENV_PATCH_JSON must be a JSON object") from None
    if not isinstance(env_patch, dict) or not all(
        isinstance(key, str) and key and isinstance(value, str)
        for key, value in env_patch.items()
    ):
        raise SystemExit("RUNTIME_ENV_PATCH_JSON must be a JSON string map")
    client = AgentkitRuntimeClient(
        access_key=_required("VOLCENGINE_ACCESS_KEY"),
        secret_key=_required("VOLCENGINE_SECRET_KEY"),
        region=os.environ.get("VOLCENGINE_REGION", "cn-beijing"),
    )
    before = client.get_runtime(GetRuntimeRequest(runtime_id=runtime_id))
    protected_before = _protected_configuration(before)
    before_envs = list(before.envs or [])
    version_before = before.current_version_number

    client.update_runtime(UpdateRuntimeRequest(
        runtime_id=runtime_id,
        artifact_type="image",
        artifact_url=image,
        envs=_apply_env_patch(before_envs, env_patch) if env_patch else None,
        release_enable=True,
    ))

    deadline = time.monotonic() + 900
    current = None
    while time.monotonic() < deadline:
        current = client.get_runtime(GetRuntimeRequest(runtime_id=runtime_id))
        if (
            current.status == "Ready"
            and current.current_version_number is not None
            and current.current_version_number > (version_before or 0)
            and current.artifact_type == "image"
            and current.artifact_url == image
        ):
            break
        if current.status in {"Failed", "Error"}:
            raise SystemExit("Runtime update failed")
        time.sleep(15)
    else:
        raise SystemExit("Runtime update did not become Ready before timeout")

    protected_after = _protected_configuration(current)
    before_without_env = dict(protected_before)
    after_without_env = dict(protected_after)
    before_without_env.pop("env_digest")
    after_without_env.pop("env_digest")
    config_unchanged = before_without_env == after_without_env
    env_patch_applied = _verify_env_patch(before_envs, current.envs or [], env_patch)
    version = client.get_runtime_version(GetRuntimeVersionRequest(
        runtime_id=runtime_id,
        version_number=current.current_version_number,
    ))
    if not version.endpoint:
        raise SystemExit("Runtime endpoint is unavailable")
    response = httpx.get(
        version.endpoint.rstrip("/") + "/health",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=180,
    )
    result = {
        "runtime_id_suffix": runtime_id[-4:],
        "version_before": version_before,
        "version_after": current.current_version_number,
        "status": current.status,
        "artifact_type_is_image": current.artifact_type == "image",
        "artifact_tag_matches": current.artifact_url == image,
        "protected_configuration_unchanged": config_unchanged,
        "env_patch_key_count": len(env_patch),
        "env_patch_applied": env_patch_applied,
        "health_http_status": response.status_code,
    }
    print(json.dumps(result, sort_keys=True))
    if not config_unchanged or not env_patch_applied or response.status_code != 200:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
