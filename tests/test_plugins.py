from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path

import pytest

from obst.cli import CliContext
from obst.conformance import StageConformanceCase
from obst.core import Extension, ExtensionRegistry
from obst.plugins import (
    COMMAND_ENTRY_POINT_GROUP,
    CONFORMANCE_ENTRY_POINT_GROUP,
    EXTENSION_ENTRY_POINT_GROUP,
    PluginConformanceError,
    PluginDiscoveryError,
    PluginLoadError,
    PluginManager,
    PluginStateError,
)
from obst_defaults.bundle import obst_extensions
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.conformance import obst_conformance

_NOT_CALLABLE = 7


def valid_plugin_factory() -> tuple[Extension, ...]:
    return (RawExtension(),)


def conflicting_plugin_factory() -> tuple[Extension, ...]:
    return (RawExtension(),)


def empty_plugin_factory() -> tuple[Extension, ...]:
    return ()


def exploding_plugin_factory() -> tuple[Extension, ...]:
    raise RuntimeError("factory exploded")


def valid_conformance_factory() -> tuple[StageConformanceCase, ...]:
    return (
        StageConformanceCase(
            stage_id=RawExtension.extension_id,
            parameters=b"",
            logical=b"known bytes",
            encoded=b"known bytes",
            canonical_encoding=True,
        ),
    )


def failing_conformance_factory() -> tuple[StageConformanceCase, ...]:
    return (
        StageConformanceCase(
            stage_id=RawExtension.extension_id,
            parameters=b"",
            logical=b"expected",
            encoded=b"different",
        ),
    )


def invalid_conformance_factory() -> tuple[object, ...]:
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


def _entry_point(name: str, target: str, group: str) -> metadata.EntryPoint:
    return metadata.EntryPoint(name=name, value=target, group=group)


def _discover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    extensions: tuple[metadata.EntryPoint, ...] = (),
    commands: tuple[metadata.EntryPoint, ...] = (),
    conformance: tuple[metadata.EntryPoint, ...] = (),
    default_enabled: tuple[str, ...] = (),
) -> PluginManager:
    entries = {
        EXTENSION_ENTRY_POINT_GROUP: extensions,
        COMMAND_ENTRY_POINT_GROUP: commands,
        CONFORMANCE_ENTRY_POINT_GROUP: conformance,
    }

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        return entries[params["group"]]

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)
    return PluginManager.discover(
        state_path=tmp_path / "plugins.json",
        default_enabled=default_enabled,
    )


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
        return tuple(
            entry
            for entry in distribution.entry_points
            if entry.group == params["group"]
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
    assert manager.runtime().commands == ()

    runtime = manager.runtime(("command-only",))
    assert runtime.registry.capabilities() == ()
    assert tuple(command.name for command in runtime.commands) == ("example-command",)


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
        manager.runtime(("one", "two"))


def test_discovery_rejects_contributions_from_different_distributions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for package_name, group, target in (
        ("extension-owner", EXTENSION_ENTRY_POINT_GROUP, "owner:extensions"),
        (
            "conformance-owner",
            CONFORMANCE_ENTRY_POINT_GROUP,
            "other:conformance",
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
        return tuple(entry for entry in all_entries if entry.group == params["group"])

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)

    with pytest.raises(PluginDiscoveryError, match="different distributions"):
        PluginManager.discover(state_path=tmp_path / "state.json")


def test_activation_state_overrides_defaults_without_loading_code(
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
        default_enabled=("obst",),
    )

    assert {item.name: item.enabled for item in manager.catalog()} == {
        "example": False,
        "obst": True,
    }
    manager.disable("obst")
    manager.enable("example")

    document = json.loads(manager.state_path.read_text(encoding="utf-8"))
    assert document == {"schema_version": 1, "enabled": ["example"]}
    rediscovered = _discover(
        monkeypatch,
        tmp_path,
        extensions=entries,
        default_enabled=("obst",),
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
    assert runtime.registry.can_encode(RawExtension.extension_id)
    assert runtime.registry.can_decode(RawExtension.extension_id)


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
    assert report.cases[0].stage_id == RawExtension.extension_id
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
    with pytest.raises(PluginConformanceError, match="StageConformanceCase"):
        manager.test("valid")


def test_plugin_without_conformance_contribution_is_explicit(
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
    )

    with pytest.raises(PluginConformanceError, match="does not publish"):
        manager.test("valid")


def test_first_party_bundle_uses_the_same_plugin_and_conformance_contracts() -> None:
    extensions = obst_extensions()
    registry = ExtensionRegistry(extensions)

    assert tuple(capability.extension_id for capability in registry.capabilities()) == (
        "obst.delta8@1",
        "obst.file@1",
        "obst.filesystem@1",
        "obst.fixed@1",
        "obst.memory@1",
        "obst.raw@1",
        "obst.stdin@1",
        "obst.zlib@1",
        "obst.zlib@2",
    )
    cases = obst_conformance()
    assert {case.stage_id for case in cases} == {
        "obst.delta8@1",
        "obst.raw@1",
        "obst.zlib@1",
        "obst.zlib@2",
    }


def test_first_party_plugin_passes_its_published_conformance_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _discover(
        monkeypatch,
        tmp_path,
        extensions=(
            _entry_point(
                "obst",
                "obst_defaults.bundle:obst_extensions",
                EXTENSION_ENTRY_POINT_GROUP,
            ),
        ),
        conformance=(
            _entry_point(
                "obst",
                "obst_defaults.conformance:obst_conformance",
                CONFORMANCE_ENTRY_POINT_GROUP,
            ),
        ),
    )

    report = manager.test("obst")

    assert report.passed is True
    assert tuple(case.stage_id for case in report.cases) == (
        "obst.raw@1",
        "obst.delta8@1",
        "obst.zlib@1",
        "obst.zlib@2",
    )
