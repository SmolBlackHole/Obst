from __future__ import annotations

import json
from pathlib import Path

import pytest

from obst.core import (
    DEFAULT_LIMIT_PROFILE,
    CoreResource,
    LimitProfile,
    ResourceCatalog,
    ResourceDefinition,
    ResourceKind,
    ResourceUnit,
)
from obst.limits import LimitManager, LimitProfileSource, LimitStateError


class ExampleResource(ResourceKind):
    ITEMS = ResourceDefinition(
        "org.example/tool@1/items",
        20,
        "Items processed by the example tool.",
        ResourceUnit.COUNT,
    )


def _catalog() -> ResourceCatalog:
    return ResourceCatalog(
        tuple(CoreResource) + tuple(ExampleResource),
        (
            DEFAULT_LIMIT_PROFILE,
            LimitProfile(
                "org.example/tool@1/strict",
                "Strict example limits.",
                ((ExampleResource.ITEMS, 2),),
            ),
        ),
    )


def test_missing_state_selects_immutable_default(tmp_path: Path) -> None:
    manager = LimitManager.discover(state_path=tmp_path / "limits.json")

    assert manager.active_profile_id == "default"
    assert manager.policy(_catalog()).maximum(CoreResource.CHUNKS) == 262_144
    default = manager.show(_catalog()).profile
    assert default.source is LimitProfileSource.DEFAULT
    assert default.active is True
    assert default.mutable is False


def test_custom_profile_stores_only_sorted_overrides_and_resolves_defaults(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "limits.json"
    manager = LimitManager.discover(state_path=state_path)
    catalog = _catalog()

    manager.create("small", catalog)
    manager.set("small", str(ExampleResource.ITEMS), None, catalog)
    manager.set("small", str(CoreResource.CHUNKS), 3, catalog)
    manager.use("small", catalog)

    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document == {
        "active_profile": "small",
        "profiles": {
            "small": {
                "chunks": 3,
                "org.example/tool@1/items": None,
            }
        },
        "schema_version": 1,
    }
    policy = LimitManager.discover(state_path=state_path).policy(catalog)
    assert policy.maximum(CoreResource.CHUNKS) == 3
    assert policy.maximum(CoreResource.STREAMS) == 65_536
    assert policy.maximum(ExampleResource.ITEMS) is None


def test_unknown_plugin_override_remains_visible_and_inert(tmp_path: Path) -> None:
    state_path = tmp_path / "limits.json"
    state_path.write_text(
        json.dumps(
            {
                "active_profile": "portable",
                "profiles": {
                    "portable": {
                        "org.example/tool@1/items": 7,
                    }
                },
                "schema_version": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manager = LimitManager.discover(state_path=state_path)
    core_catalog = ResourceCatalog(tuple(CoreResource), (DEFAULT_LIMIT_PROFILE,))

    view = manager.show(core_catalog)
    retained = next(
        resource
        for resource in view.resources
        if resource.resource_id == "org.example/tool@1/items"
    )
    assert retained.available is False
    assert retained.resolved_maximum == 7
    assert manager.policy(core_catalog).maximum(CoreResource.CHUNKS) == 262_144


def test_contributed_profile_requires_explicit_selection(tmp_path: Path) -> None:
    manager = LimitManager.discover(state_path=tmp_path / "limits.json")
    catalog = _catalog()

    assert manager.policy(catalog).maximum(ExampleResource.ITEMS) == 20
    contributed = manager.use("org.example/tool@1/strict", catalog)
    assert contributed.source is LimitProfileSource.PLUGIN
    assert manager.policy(catalog).maximum(ExampleResource.ITEMS) == 2


def test_unavailable_selected_contributed_profile_fails_explicitly(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "limits.json"
    manager = LimitManager.discover(state_path=state_path)
    manager.use("org.example/tool@1/strict", _catalog())
    core_catalog = ResourceCatalog(tuple(CoreResource), (DEFAULT_LIMIT_PROFILE,))

    status = next(status for status in manager.profiles(core_catalog) if status.active)
    assert status.available is False
    with pytest.raises(LimitStateError, match="selected profile is unavailable"):
        manager.policy(core_catalog)


def test_default_and_active_custom_profiles_cannot_be_mutated_or_deleted(
    tmp_path: Path,
) -> None:
    manager = LimitManager.discover(state_path=tmp_path / "limits.json")
    catalog = _catalog()

    with pytest.raises(LimitStateError, match="immutable"):
        manager.set("default", "chunks", 1, catalog)
    with pytest.raises(LimitStateError, match="immutable"):
        manager.delete("default", catalog)

    manager.create("custom", catalog)
    manager.use("custom", catalog)
    with pytest.raises(LimitStateError, match="active profile"):
        manager.delete("custom", catalog)


def test_unknown_new_resource_is_rejected_but_retained_resource_can_change(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "limits.json"
    manager = LimitManager.discover(state_path=state_path)
    catalog = _catalog()
    manager.create("custom", catalog)
    manager.set("custom", str(ExampleResource.ITEMS), 5, catalog)

    with pytest.raises(LimitStateError, match="unknown resource"):
        manager.set("custom", "org.example/missing@1/items", 1, catalog)

    core_catalog = ResourceCatalog(tuple(CoreResource), (DEFAULT_LIMIT_PROFILE,))
    changed = manager.set(
        "custom",
        str(ExampleResource.ITEMS),
        8,
        core_catalog,
    )
    assert changed.available is False
    assert changed.resolved_maximum == 8


@pytest.mark.parametrize(
    "document",
    (
        {"schema_version": 1, "active_profile": "default", "profiles": []},
        {"schema_version": 2, "active_profile": "default", "profiles": {}},
        {
            "schema_version": 1,
            "active_profile": "default",
            "profiles": {"default": {}},
        },
        {
            "schema_version": 1,
            "active_profile": "custom",
            "profiles": {"custom": {"chunks": True}},
        },
    ),
)
def test_invalid_limit_state_is_rejected(
    tmp_path: Path,
    document: object,
) -> None:
    state_path = tmp_path / "limits.json"
    state_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LimitStateError):
        LimitManager.discover(state_path=state_path)
