from __future__ import annotations

import argparse
import json
from email.message import Message
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import pytest

from obst.cli import CliContext
from obst.conformance import (
    ConformanceSuite,
    StageKnownAnswerCase,
)
from obst.core import (
    Extension,
)
from obst.plugins import (
    COMMAND_ENTRY_POINT_GROUP,
    CONFORMANCE_ENTRY_POINT_GROUP,
    EXTENSION_ENTRY_POINT_GROUP,
    RESOURCE_ENTRY_POINT_GROUP,
    PluginConformanceError,
    PluginDiscoveryError,
    PluginLoadError,
    PluginManager,
    PluginStateError,
)
from obst.resources import (
    LimitProfile,
    ResourceAggregation,
    ResourceContribution,
    ResourceDefinition,
    ResourceKind,
    ResourceUnit,
)
from tests.support_extensions import IdentityExtension

_NOT_CALLABLE = 7


class _StubDistribution:
    def __init__(self, name: str) -> None:
        package_metadata = Message()
        package_metadata["Name"] = name
        package_metadata["Version"] = "1.0"
        self.name = name
        self.version = "1.0"
        self.metadata = cast(metadata.PackageMetadata, package_metadata)


def valid_plugin_factory() -> tuple[Extension, ...]:
    return (IdentityExtension(),)


def conflicting_plugin_factory() -> tuple[Extension, ...]:
    return (IdentityExtension(),)


def empty_plugin_factory() -> tuple[Extension, ...]:
    return ()


def exploding_plugin_factory() -> tuple[Extension, ...]:
    raise RuntimeError("factory exploded")


def valid_conformance_factory() -> ConformanceSuite:
    return ConformanceSuite(
        (
            StageKnownAnswerCase(
                "identity-known-answer",
                IdentityExtension.extension_id,
                b"",
                b"known bytes",
                b"known bytes",
                canonical_encoding=True,
            ),
        ),
    )


def failing_conformance_factory() -> ConformanceSuite:
    return ConformanceSuite(
        (
            StageKnownAnswerCase(
                "identity-known-answer",
                IdentityExtension.extension_id,
                b"",
                b"expected",
                b"different",
            ),
        ),
    )


def invalid_conformance_factory() -> tuple[object, ...]:
    return (object(),)


class ExampleResource(ResourceKind):
    ITEMS = ResourceDefinition(
        f"{IdentityExtension.extension_id}/items",
        8,
        "Items processed by the example plugin.",
        ResourceUnit.COUNT,
        ResourceAggregation.TOTAL,
    )


class UnqualifiedResource(ResourceKind):
    ITEMS = ResourceDefinition(
        "unqualified_items",
        8,
        "Invalid unqualified plugin resource.",
        ResourceUnit.COUNT,
        ResourceAggregation.TOTAL,
    )


def valid_resource_factory() -> ResourceContribution:
    return ResourceContribution(
        tuple(ExampleResource),
        (
            LimitProfile(
                f"{IdentityExtension.extension_id}/strict",
                "Strict example limits.",
                ((ExampleResource.ITEMS, 2),),
            ),
        ),
    )


def duplicate_resource_factory() -> ResourceContribution:
    return ResourceContribution(
        (ExampleResource.ITEMS, ExampleResource.ITEMS),
    )


def unqualified_resource_factory() -> ResourceContribution:
    return ResourceContribution(tuple(UnqualifiedResource))


def invalid_resource_factory() -> tuple[object, ...]:
    return (object(),)


class _ExampleCommand:
    name = "example-command"
    summary = "exercise one plugin-contributed command"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--value", default="worked")

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        context.stdout.write(f"{args.value}\n")
        return 0


def valid_command_factory() -> tuple[_ExampleCommand, ...]:
    return (_ExampleCommand(),)


class _RaisingNameCommand:
    @property
    def name(self) -> str:
        raise RuntimeError("name getter exploded")

    summary = "raise while the host captures the command"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        return 0


def raising_name_command_factory() -> tuple[_RaisingNameCommand, ...]:
    return (_RaisingNameCommand(),)


class _InvalidExitCommand(_ExampleCommand):
    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        return "not-an-int"  # type: ignore[return-value]


def invalid_exit_command_factory() -> tuple[_InvalidExitCommand, ...]:
    return (_InvalidExitCommand(),)


class _MutableCommand(_ExampleCommand):
    def __init__(self) -> None:
        self.name = "captured-command"
        self.summary = "captured summary"


_MUTABLE_COMMAND = _MutableCommand()


def mutable_command_factory() -> tuple[_MutableCommand, ...]:
    return (_MUTABLE_COMMAND,)


def _entry_point(name: str, target: str, group: str) -> metadata.EntryPoint:
    return metadata.EntryPoint(name=name, value=target, group=group)


def _discover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    extensions: tuple[metadata.EntryPoint, ...] = (),
    commands: tuple[metadata.EntryPoint, ...] = (),
    conformance: tuple[metadata.EntryPoint, ...] = (),
    resources: tuple[metadata.EntryPoint, ...] = (),
    auto_conformance: bool = True,
) -> PluginManager:
    if auto_conformance and extensions and not conformance:
        conformance = tuple(
            _entry_point(
                name,
                f"{__name__}:valid_conformance_factory",
                CONFORMANCE_ENTRY_POINT_GROUP,
            )
            for name in sorted({entry.name for entry in extensions})
        )
    entries = {
        EXTENSION_ENTRY_POINT_GROUP: extensions,
        COMMAND_ENTRY_POINT_GROUP: commands,
        CONFORMANCE_ENTRY_POINT_GROUP: conformance,
        RESOURCE_ENTRY_POINT_GROUP: resources,
    }

    all_entries = extensions + commands + conformance + resources
    entries_by_name: dict[str, list[metadata.EntryPoint]] = {}
    for entry in all_entries:
        entries_by_name.setdefault(entry.name, []).append(entry)
    for name, owned_entries in entries_by_name.items():
        if len(owned_entries) > 1:
            owner = _StubDistribution(name)
            for entry in owned_entries:
                cast(Any, entry)._for(owner)

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        if group is None:
            return all_entries
        return entries[group]

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)
    return PluginManager.discover(state_path=tmp_path / "plugins.json")


def test_discovery_is_inert_and_sorted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                "z-last",
                "not.imported:factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
            _entry_point(
                "a-first",
                "also.not.imported:factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
    )

    assert tuple(plugin.name for plugin in manager.catalog()) == (
        "a-first",
        "z-last",
    )
    assert tuple(plugin.extension_reference for plugin in manager.catalog()) == (
        "also.not.imported:factory",
        "not.imported:factory",
    )


def test_selected_plugin_contributes_typed_resources_and_inert_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_name = "example"
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                plugin_name,
                f"{__name__}:valid_plugin_factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
        resources=(
            _entry_point(
                plugin_name,
                f"{__name__}:valid_resource_factory",
                RESOURCE_ENTRY_POINT_GROUP,
            ),
        ),
    )

    disabled_runtime = manager.runtime()
    assert str(ExampleResource.ITEMS) not in {
        str(resource) for resource in disabled_runtime.resources.resources
    }

    runtime = manager.runtime((plugin_name,))
    assert (
        runtime.resources.resource(str(ExampleResource.ITEMS)) is ExampleResource.ITEMS
    )
    policy = runtime.resources.policy(f"{IdentityExtension.extension_id}/strict")
    assert policy.maximum(ExampleResource.ITEMS) == 2
    assert manager.status(plugin_name).resource_reference == (
        f"{__name__}:valid_resource_factory"
    )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        ("invalid_resource_factory", "exact ResourceContribution"),
        ("duplicate_resource_factory", "duplicate resource identifier"),
        ("unqualified_resource_factory", "must be qualified"),
    ],
)
def test_resource_contribution_failures_are_explicit(
    factory: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_name = "example"
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                plugin_name,
                f"{__name__}:valid_plugin_factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
        resources=(
            _entry_point(
                plugin_name,
                f"{__name__}:{factory}",
                RESOURCE_ENTRY_POINT_GROUP,
            ),
        ),
    )

    with pytest.raises(PluginLoadError, match=message):
        manager.runtime((plugin_name,))


def test_discovery_reads_inert_standard_distribution_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_info = tmp_path / "obst-example-1.2.3.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "\n".join(
            (
                "Metadata-Version: 2.4",
                "Name: obst-example",
                "Version: 1.2.3",
                "Summary: Example extension bundle",
                "Project-URL: Documentation, https://example.com/obst",
                "",
            )
        ),
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "\n".join(
            (
                f"[{EXTENSION_ENTRY_POINT_GROUP}]",
                "example = example:extensions",
                f"[{CONFORMANCE_ENTRY_POINT_GROUP}]",
                "example = example:conformance",
                "",
            )
        ),
        encoding="utf-8",
    )
    distribution = next(iter(metadata.distributions(path=[str(tmp_path)])))

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        return tuple(
            entry
            for entry in distribution.entry_points
            if group is None or entry.group == group
        )

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)
    manager = PluginManager.discover(state_path=tmp_path / "state.json")

    assert manager.catalog()[0].distribution_name == "obst-example"
    assert manager.catalog()[0].distribution_version == "1.2.3"
    assert manager.catalog()[0].summary == "Example extension bundle"
    assert manager.catalog()[0].documentation_url == "https://example.com/obst"
    assert manager.catalog()[0].conformance_reference == "example:conformance"


@pytest.mark.parametrize("name", ("", "Uppercase", "space name", "slash/name"))
def test_discovery_rejects_noncanonical_plugin_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    with pytest.raises(PluginDiscoveryError, match="lowercase ASCII"):
        _discover(
            monkeypatch,
            tmp_path,
            extensions=(
                _entry_point(name, "example:factory", EXTENSION_ENTRY_POINT_GROUP),
            ),
        )


def test_discovery_rejects_duplicate_contributions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(PluginDiscoveryError, match="duplicate entry-point name"):
        _discover(
            monkeypatch,
            tmp_path,
            extensions=(
                _entry_point("same", "one:factory", EXTENSION_ENTRY_POINT_GROUP),
                _entry_point("same", "two:factory", EXTENSION_ENTRY_POINT_GROUP),
            ),
        )


def test_command_only_plugin_is_inert_until_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        commands=(
            _entry_point(
                "command-only",
                f"{__name__}:valid_command_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
        ),
    )

    status = manager.catalog()[0]
    assert status.extension_reference is None
    assert status.command_reference == f"{__name__}:valid_command_factory"
    assert manager.commands() == ()
    assert manager.runtime(("command-only",)).registry.capabilities() == ()

    manager.enable("command-only")
    assert tuple(command.name for command in manager.commands()) == ("example-command",)


def test_one_shot_plugin_selection_loads_extensions_but_not_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                "one-shot",
                f"{__name__}:valid_plugin_factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
        commands=(
            _entry_point(
                "one-shot",
                f"{__name__}:exploding_plugin_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
        ),
    )

    runtime = manager.runtime(("one-shot",))

    assert runtime.registry.can_decode(IdentityExtension.extension_id)
    assert manager.commands() == ()


def test_command_contract_is_captured_once_and_validates_exit_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _MUTABLE_COMMAND.name = "captured-command"
    _MUTABLE_COMMAND.summary = "captured summary"
    manager = _discover(
        monkeypatch,
        tmp_path,
        commands=(
            _entry_point(
                "mutable",
                f"{__name__}:mutable_command_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
        ),
    )
    manager.enable("mutable")
    command = manager.commands()[0]
    _MUTABLE_COMMAND.name = "changed-after-capture"
    _MUTABLE_COMMAND.summary = "changed after capture"

    assert command.name == "captured-command"
    assert command.summary == "captured summary"

    invalid_manager = _discover(
        monkeypatch,
        tmp_path / "invalid-exit",
        commands=(
            _entry_point(
                "invalid-exit",
                f"{__name__}:invalid_exit_command_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
        ),
    )
    invalid_manager.enable("invalid-exit")
    invalid = invalid_manager.commands()[0]
    with pytest.raises(PluginLoadError, match=r"exact integer in 0\.\.255"):
        invalid.run(argparse.Namespace(), CliContext.__new__(CliContext))


def test_command_attribute_failures_use_the_plugin_error_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        commands=(
            _entry_point(
                "raising",
                f"{__name__}:raising_name_command_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
        ),
    )
    manager.enable("raising")

    with pytest.raises(PluginLoadError, match="name getter exploded"):
        manager.commands()


def test_duplicate_plugin_command_names_are_rejected_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        commands=(
            _entry_point(
                "one",
                f"{__name__}:valid_command_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
            _entry_point(
                "two",
                f"{__name__}:valid_command_factory",
                COMMAND_ENTRY_POINT_GROUP,
            ),
        ),
    )

    with pytest.raises(PluginLoadError, match="already provided"):
        manager.enable("one")
        manager.enable("two")
        manager.commands()


@pytest.mark.parametrize(
    "second_group",
    [CONFORMANCE_ENTRY_POINT_GROUP, RESOURCE_ENTRY_POINT_GROUP],
)
def test_discovery_rejects_contributions_from_different_distributions(
    second_group: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for package_name, group, target in (
        ("extension-owner", EXTENSION_ENTRY_POINT_GROUP, "owner:extensions"),
        (
            "conformance-owner",
            second_group,
            "other:contribution",
        ),
    ):
        dist_info = tmp_path / f"{package_name}-1.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            "\n".join(
                (
                    "Metadata-Version: 2.4",
                    f"Name: {package_name}",
                    "Version: 1.0",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (dist_info / "entry_points.txt").write_text(
            f"[{group}]\nsame = {target}\n",
            encoding="utf-8",
        )
    all_entries = tuple(
        entry
        for distribution in metadata.distributions(path=[str(tmp_path)])
        for entry in distribution.entry_points
    )

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        return tuple(
            entry for entry in all_entries if group is None or entry.group == group
        )

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)

    with pytest.raises(PluginDiscoveryError, match="different distributions"):
        PluginManager.discover(state_path=tmp_path / "state.json")


def test_discovery_rejects_distinct_owners_with_equal_declared_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extension = _entry_point(
        "same",
        "owner:extensions",
        EXTENSION_ENTRY_POINT_GROUP,
    )
    command = _entry_point(
        "same",
        "owner:commands",
        COMMAND_ENTRY_POINT_GROUP,
    )
    conformance = _entry_point(
        "same",
        "owner:conformance",
        CONFORMANCE_ENTRY_POINT_GROUP,
    )
    extension_owner = _StubDistribution("same-owner")
    cast(Any, extension)._for(extension_owner)
    cast(Any, conformance)._for(extension_owner)
    cast(Any, command)._for(_StubDistribution("same-owner"))

    def installed_entry_points(**_params: str) -> tuple[metadata.EntryPoint, ...]:
        return extension, command, conformance

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)

    with pytest.raises(PluginDiscoveryError, match="different distributions"):
        PluginManager.discover(state_path=tmp_path / "state.json")


def test_activation_requires_explicit_persisted_state_without_loading_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = (
        _entry_point(
            "obst",
            "module.that.must.not.load:factory",
            EXTENSION_ENTRY_POINT_GROUP,
        ),
        _entry_point(
            "example",
            "another.module.that.must.not.load:factory",
            EXTENSION_ENTRY_POINT_GROUP,
        ),
    )
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=entries,
    )

    assert {item.name: item.enabled for item in manager.catalog()} == {
        "example": False,
        "obst": False,
    }
    manager.enable("example")

    document = json.loads(manager.state_path.read_text(encoding="utf-8"))
    assert document == {"schema_version": 1, "enabled": ["example"]}
    rediscovered = _discover(
        monkeypatch,
        tmp_path,
        extensions=entries,
    )
    assert {item.name: item.enabled for item in rediscovered.catalog()} == {
        "example": True,
        "obst": False,
    }


def test_corrupt_or_noncanonical_state_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "plugins.json"
    state_path.write_text(
        '{"schema_version": 1, "enabled": ["z", "a"]}',
        encoding="utf-8",
    )

    def no_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        return ()

    monkeypatch.setattr(metadata, "entry_points", no_entry_points)

    with pytest.raises(PluginStateError, match="must be sorted"):
        PluginManager.discover(state_path=state_path)


@pytest.mark.parametrize("schema_version", (True, 1.0))
def test_plugin_state_requires_an_exact_integer_schema_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_version: object,
) -> None:
    state_path = tmp_path / "plugins.json"
    state_path.write_text(
        json.dumps({"schema_version": schema_version, "enabled": []}),
        encoding="utf-8",
    )

    def no_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        return ()

    monkeypatch.setattr(metadata, "entry_points", no_entry_points)

    with pytest.raises(PluginStateError, match="schema version"):
        PluginManager.discover(state_path=state_path)


def test_enabled_but_missing_plugin_remains_visible_and_fails_at_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "plugins.json"
    state_path.write_text(
        '{"enabled": ["gone"], "schema_version": 1}\n',
        encoding="utf-8",
    )

    def no_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        return ()

    monkeypatch.setattr(metadata, "entry_points", no_entry_points)
    manager = PluginManager.discover(state_path=state_path)

    assert manager.catalog()[0].installed is False
    with pytest.raises(PluginDiscoveryError, match="no longer installed"):
        manager.runtime()
    assert manager.disable("gone").enabled is False


def test_runtime_loads_enabled_plugins_and_explicit_additions_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = (
        _entry_point(
            "valid",
            f"{__name__}:valid_plugin_factory",
            EXTENSION_ENTRY_POINT_GROUP,
        ),
    )
    manager = _discover(monkeypatch, tmp_path, extensions=entries)

    assert manager.runtime().registry.capabilities() == ()
    runtime = manager.runtime(("valid", "valid"))
    assert runtime.plugin_names == ("valid",)
    assert runtime.registry.can_encode(IdentityExtension.extension_id)
    assert runtime.registry.can_decode(IdentityExtension.extension_id)


@pytest.mark.parametrize(
    ("target", "message"),
    (
        (f"{__name__}:_NOT_CALLABLE", "must resolve to a callable"),
        (f"{__name__}:empty_plugin_factory", "non-empty exact tuple"),
        (f"{__name__}:exploding_plugin_factory", "factory raised RuntimeError"),
        (
            "module.that.does.not.exist:factory",
            "entry point raised ModuleNotFoundError",
        ),
    ),
)
def test_runtime_wraps_entry_point_and_factory_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    message: str,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(_entry_point("broken", target, EXTENSION_ENTRY_POINT_GROUP),),
    )

    with pytest.raises(PluginLoadError, match=message):
        manager.runtime(("broken",))


def test_runtime_reports_registry_conflicts_as_plugin_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                "one",
                f"{__name__}:valid_plugin_factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
            _entry_point(
                "two",
                f"{__name__}:conflicting_plugin_factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
    )

    with pytest.raises(PluginLoadError, match="registry rejected"):
        manager.runtime(("one", "two"))


def test_plugin_conformance_is_explicit_and_renderer_neutral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extension_entry = _entry_point(
        "valid",
        f"{__name__}:valid_plugin_factory",
        EXTENSION_ENTRY_POINT_GROUP,
    )
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(extension_entry,),
        conformance=(
            _entry_point(
                "valid",
                f"{__name__}:valid_conformance_factory",
                CONFORMANCE_ENTRY_POINT_GROUP,
            ),
        ),
    )

    report = manager.test("valid")

    assert report.passed is True
    assert report.cases[0].case_id == "identity-known-answer"
    assert report.cases[0].extension_id == IdentityExtension.extension_id
    assert report.cases[0].error is None


def test_plugin_conformance_reports_case_failures_and_bad_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extension_entry = _entry_point(
        "valid",
        f"{__name__}:valid_plugin_factory",
        EXTENSION_ENTRY_POINT_GROUP,
    )
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(extension_entry,),
        conformance=(
            _entry_point(
                "valid",
                f"{__name__}:failing_conformance_factory",
                CONFORMANCE_ENTRY_POINT_GROUP,
            ),
        ),
    )
    assert manager.test("valid").passed is False

    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(extension_entry,),
        conformance=(
            _entry_point(
                "valid",
                f"{__name__}:invalid_conformance_factory",
                CONFORMANCE_ENTRY_POINT_GROUP,
            ),
        ),
    )
    with pytest.raises(PluginConformanceError, match="ConformanceSuite"):
        manager.test("valid")


def test_extension_plugin_without_conformance_can_run_but_not_be_tested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                "valid",
                f"{__name__}:valid_plugin_factory",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
        auto_conformance=False,
    )

    runtime = manager.runtime(additional=("valid",))
    assert runtime.registry.can_decode(IdentityExtension.extension_id)

    with pytest.raises(PluginConformanceError, match="does not publish"):
        manager.test("valid")
