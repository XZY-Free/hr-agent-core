from agentkit.sdk.runtime.types import (
    EnvsForGetRuntime,
    GetRuntimeResponse,
    NetworkConfigurationsForGetRuntime,
)

from scripts.update_runtime_image import (
    _apply_env_patch,
    _protected_configuration,
    _stable_digest,
    _verify_env_patch,
)


def test_stable_digest_serializes_lists_of_runtime_models():
    value = [NetworkConfigurationsForGetRuntime(network_type="public")]

    assert _stable_digest(value) == _stable_digest(value)


def test_protected_configuration_ignores_environment_order_only():
    first = GetRuntimeResponse(envs=[
        EnvsForGetRuntime(key="B", value="two"),
        EnvsForGetRuntime(key="A", value="one"),
    ])
    second = GetRuntimeResponse(envs=[
        EnvsForGetRuntime(key="A", value="one"),
        EnvsForGetRuntime(key="B", value="two"),
    ])

    assert _protected_configuration(first) == _protected_configuration(second)


def test_env_patch_changes_only_named_values_and_preserves_all_other_entries():
    before = [
        EnvsForGetRuntime(key="UNCHANGED", value="same"),
        EnvsForGetRuntime(key="REPLACED", value="old"),
    ]

    updated = _apply_env_patch(before, {"REPLACED": "new", "ADDED": "value"})

    assert {item.key: item.value for item in updated} == {
        "ADDED": "value",
        "REPLACED": "new",
        "UNCHANGED": "same",
    }
    assert _verify_env_patch(before, updated, {
        "REPLACED": "new",
        "ADDED": "value",
    })


def test_env_patch_verification_rejects_an_unrelated_change():
    before = [EnvsForGetRuntime(key="UNCHANGED", value="same")]
    after = [EnvsForGetRuntime(key="UNCHANGED", value="changed")]

    assert not _verify_env_patch(before, after, {})
