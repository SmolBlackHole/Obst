"""Installed plugin discovery, activation and runtime composition."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import cast

from obst.cli.commands import CliCommand, CliContext
from obst.conformance import (
    ConformanceError,
    ConformanceSuite,
    PluginConformanceReport,
    check_plugin_conformance,
)
from obst.core.errors import ExtensionError, ObstError
from obst.core.extensions import Extension
from obst.core.registry import ExtensionRegistry

EXTENSION_ENTRY_POINT_GROUP = "obst.extensions"
COMMAND_ENTRY_POINT_GROUP = "obst.commands"
CONFORMANCE_ENTRY_POINT_GROUP = "obst.conformance"
PLUGIN_STATE_SCHEMA_VERSION = 1

_PLUGIN_NAME_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")


class PluginError(ObstError):
    """Base class for installed plugin management failures."""


class PluginDiscoveryError(PluginError):
    """Installed plugin metadata is ambiguous or violates its host contract."""

    def __init__(self, plugin_name: str, reason: str) -> None:
        self.plugin_name = plugin_name
        self.reason = reason
        super().__init__(f"cannot discover plugin {plugin_name}: {reason}")


class PluginStateError(PluginError):
    """The local enabled-plugin state is invalid or cannot be persisted."""

    def __init__(self, state_path: Path, reason: str) -> None:
        self.state_path = state_path
        self.reason = reason
        super().__init__(f"cannot use plugin state {state_path}: {reason}")


class PluginLoadError(PluginError):
    """A selected trusted plugin could not produce valid extension values."""

    def __init__(self, plugin_name: str, reason: str) -> None:
        self.plugin_name = plugin_name
        self.reason = reason
        super().__init__(f"cannot load plugin {plugin_name}: {reason}")


class PluginConformanceError(PluginError):
    """A plugin cannot expose or execute its declared conformance cases."""

    def __init__(self, plugin_name: str, reason: str) -> None:
        self.plugin_name = plugin_name
        self.reason = reason
        super().__init__(f"cannot test plugin {plugin_name}: {reason}")


@dataclass(frozen=True, slots=True)
class PluginStatus:
    """Inert installed metadata and local activation state for one plugin."""

    name: str
    installed: bool
    enabled: bool
    default: bool
    distribution_name: str | None = None
    distribution_version: str | None = None
    summary: str | None = None
    documentation_url: str | None = None
    extension_reference: str | None = None
    command_reference: str | None = None
    conformance_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PluginRuntime:
    """One immutable registry built from an explicitly selected plugin set."""

    plugin_names: tuple[str, ...]
    registry: ExtensionRegistry


@dataclass(frozen=True, slots=True)
class _CapturedCliCommand:
    plugin_name: str
    name: str
    summary: str
    _configure_parser: Callable[[argparse.ArgumentParser], None]
    _run: Callable[[argparse.Namespace, CliContext], object]

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        try:
            self._configure_parser(parser)
        except Exception as exc:
            raise PluginLoadError(
                self.plugin_name,
                f"command {self.name} configure_parser raised "
                f"{type(exc).__name__}: {exc}",
            ) from exc

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        try:
            result = self._run(args, context)
        except ObstError:
            raise
        except Exception as exc:
            raise PluginLoadError(
                self.plugin_name,
                f"command {self.name} run raised {type(exc).__name__}: {exc}",
            ) from exc
        if type(result) is not int or not 0 <= result <= 255:
            raise PluginLoadError(
                self.plugin_name,
                f"command {self.name} must return an exact integer in 0..255",
            )
        return result


@dataclass(frozen=True, slots=True)
class _InstalledPlugin:
    name: str
    extension_entry_point: metadata.EntryPoint | None
    command_entry_point: metadata.EntryPoint | None
    conformance_entry_point: metadata.EntryPoint | None
    distribution_name: str | None
    distribution_version: str | None
    summary: str | None
    documentation_url: str | None


class PluginManager:
    """Discover installed plugins and compose explicitly trusted runtimes."""

    def __init__(
        self,
        *,
        installed: dict[str, _InstalledPlugin],
        state_path: Path,
        default_enabled: frozenset[str],
    ) -> None:
        self._installed = installed
        self._state_path = state_path
        self._default_enabled = default_enabled
        self._enabled = _read_enabled_plugins(state_path, default_enabled)

    @classmethod
    def discover(
        cls,
        *,
        state_path: Path | None = None,
        default_enabled: Iterable[str] = (),
    ) -> PluginManager:
        """Discover plugin metadata without importing plugin code."""
        defaults = frozenset(default_enabled)
        for name in defaults:
            _validate_plugin_name(name)
        entry_points = tuple(metadata.entry_points())
        extension_entries = _index_entry_points(
            entry_points,
            EXTENSION_ENTRY_POINT_GROUP,
        )
        command_entries = _index_entry_points(
            entry_points,
            COMMAND_ENTRY_POINT_GROUP,
        )
        conformance_entries = _index_entry_points(
            entry_points,
            CONFORMANCE_ENTRY_POINT_GROUP,
        )
        installed: dict[str, _InstalledPlugin] = {}
        names = (
            extension_entries.keys()
            | command_entries.keys()
            | conformance_entries.keys()
        )
        for name in sorted(names):
            extension_entry = extension_entries.get(name)
            command_entry = command_entries.get(name)
            conformance_entry = conformance_entries.get(name)
            if extension_entry is not None and conformance_entry is None:
                raise PluginDiscoveryError(
                    name,
                    f"plugins that publish {EXTENSION_ENTRY_POINT_GROUP} must also "
                    f"publish {CONFORMANCE_ENTRY_POINT_GROUP}",
                )
            if conformance_entry is not None and extension_entry is None:
                raise PluginDiscoveryError(
                    name,
                    f"{CONFORMANCE_ENTRY_POINT_GROUP} requires a matching "
                    f"{EXTENSION_ENTRY_POINT_GROUP} contribution",
                )
            entries = tuple(
                entry
                for entry in (extension_entry, command_entry, conformance_entry)
                if entry is not None
            )
            _require_same_distribution(name, entries)
            distribution = entries[0].dist
            summary, documentation_url = _describe_distribution(distribution)
            installed[name] = _InstalledPlugin(
                name=name,
                extension_entry_point=extension_entry,
                command_entry_point=command_entry,
                conformance_entry_point=conformance_entry,
                distribution_name=(None if distribution is None else distribution.name),
                distribution_version=(
                    None if distribution is None else distribution.version
                ),
                summary=summary,
                documentation_url=documentation_url,
            )
        return cls(
            installed=installed,
            state_path=state_path or default_plugin_state_path(),
            default_enabled=defaults,
        )

    @property
    def state_path(self) -> Path:
        """Return the local activation-state file used by this manager."""
        return self._state_path

    def catalog(self) -> tuple[PluginStatus, ...]:
        """Return inert metadata for installed and enabled-but-missing plugins."""
        names = self._installed.keys() | self._enabled
        return tuple(self._status(name) for name in sorted(names))

    def status(self, name: str) -> PluginStatus:
        """Return inert metadata and activation state for one known plugin."""
        _validate_plugin_name(name)
        if name not in self._installed and name not in self._enabled:
            raise PluginDiscoveryError(name, "plugin is not installed or enabled")
        return self._status(name)

    def enable(self, name: str) -> PluginStatus:
        """Persistently enable one installed plugin without loading its code."""
        plugin = self._require_installed(name)
        if name not in self._enabled:
            enabled = self._enabled | {name}
            _write_enabled_plugins(self._state_path, enabled)
            self._enabled = enabled
        return self._status(plugin.name)

    def disable(self, name: str) -> PluginStatus:
        """Persistently disable one installed or stale enabled plugin."""
        _validate_plugin_name(name)
        if name not in self._installed and name not in self._enabled:
            raise PluginDiscoveryError(name, "plugin is not installed or enabled")
        if name in self._enabled:
            enabled = self._enabled - {name}
            _write_enabled_plugins(self._state_path, enabled)
            self._enabled = enabled
        return self._status(name)

    def runtime(self, additional: Iterable[str] = ()) -> PluginRuntime:
        """Load extension capabilities from enabled and one-shot plugins."""
        selected = list(sorted(self._enabled))
        seen = set(selected)
        for name in additional:
            _validate_plugin_name(name)
            if name in seen:
                continue
            seen.add(name)
            selected.append(name)
        extensions: list[Extension] = []
        for name in selected:
            plugin = self._require_installed(name)
            extensions.extend(self._load_extensions(plugin))
        try:
            registry = ExtensionRegistry(tuple(extensions))
        except ExtensionError as exc:
            names = ", ".join(selected) or "<none>"
            raise PluginLoadError(
                names,
                f"extension registry rejected the selected plugin set: {exc}",
            ) from exc
        return PluginRuntime(
            tuple(selected),
            registry,
        )

    def commands(self) -> tuple[CliCommand, ...]:
        """Load and capture commands from persistently enabled plugins."""
        commands: list[CliCommand] = []
        command_owners: dict[str, str] = {}
        for name in sorted(self._enabled):
            plugin = self._require_installed(name)
            for command in self._load_commands(plugin):
                owner = command_owners.get(command.name)
                if owner is not None:
                    raise PluginLoadError(
                        name,
                        f"command {command.name} is already provided by plugin {owner}",
                    )
                command_owners[command.name] = name
                commands.append(command)
        return tuple(sorted(commands, key=lambda command: command.name))

    def test(
        self,
        name: str,
        additional: Iterable[str] = (),
    ) -> PluginConformanceReport:
        """Run one plugin's explicitly published portable conformance cases."""
        plugin = self._require_installed(name)
        entry_point = plugin.conformance_entry_point
        if entry_point is None:
            raise PluginConformanceError(
                name,
                f"plugin does not publish {CONFORMANCE_ENTRY_POINT_GROUP}",
            )
        owned_extensions = self._load_extensions(plugin)
        extensions = list(owned_extensions)
        selected = {name}
        for dependency_name in additional:
            _validate_plugin_name(dependency_name)
            if dependency_name in selected:
                continue
            selected.add(dependency_name)
            dependency = self._require_installed(dependency_name)
            extensions.extend(self._load_extensions(dependency))
        try:
            owned_registry = ExtensionRegistry(owned_extensions)
            registry = ExtensionRegistry(tuple(extensions))
        except ExtensionError as exc:
            raise PluginConformanceError(
                name,
                f"extension registry rejected the selected plugin set: {exc}",
            ) from exc
        suite = _load_conformance_suite(name, entry_point)
        try:
            return check_plugin_conformance(
                name,
                registry,
                suite,
                owned_capabilities=owned_registry.capabilities(),
            )
        except ConformanceError as exc:
            raise PluginConformanceError(name, str(exc)) from exc

    def _status(self, name: str) -> PluginStatus:
        plugin = self._installed.get(name)
        if plugin is None:
            return PluginStatus(
                name=name,
                installed=False,
                enabled=name in self._enabled,
                default=name in self._default_enabled,
            )
        conformance_entry = plugin.conformance_entry_point
        extension_entry = plugin.extension_entry_point
        command_entry = plugin.command_entry_point
        return PluginStatus(
            name=name,
            installed=True,
            enabled=name in self._enabled,
            default=name in self._default_enabled,
            distribution_name=plugin.distribution_name,
            distribution_version=plugin.distribution_version,
            summary=plugin.summary,
            documentation_url=plugin.documentation_url,
            extension_reference=(
                None if extension_entry is None else extension_entry.value
            ),
            command_reference=None if command_entry is None else command_entry.value,
            conformance_reference=(
                None if conformance_entry is None else conformance_entry.value
            ),
        )

    def _require_installed(self, name: str) -> _InstalledPlugin:
        _validate_plugin_name(name)
        try:
            return self._installed[name]
        except KeyError as exc:
            reason = (
                "enabled plugin is no longer installed"
                if name in self._enabled
                else "plugin is not installed"
            )
            raise PluginDiscoveryError(name, reason) from exc

    @staticmethod
    def _load_extensions(plugin: _InstalledPlugin) -> tuple[Extension, ...]:
        if plugin.extension_entry_point is None:
            return ()
        values = _load_factory(
            plugin.name,
            plugin.extension_entry_point,
            error_factory=PluginLoadError,
        )
        return cast(tuple[Extension, ...], values)

    @staticmethod
    def _load_commands(plugin: _InstalledPlugin) -> tuple[CliCommand, ...]:
        entry_point = plugin.command_entry_point
        if entry_point is None:
            return ()
        values = _load_factory(
            plugin.name,
            entry_point,
            error_factory=PluginLoadError,
        )
        commands: list[CliCommand] = []
        for value in values:
            try:
                name = getattr(value, "name", None)
                summary = getattr(value, "summary", None)
                configure_parser = getattr(value, "configure_parser", None)
                run = getattr(value, "run", None)
            except Exception as exc:
                raise PluginLoadError(
                    plugin.name,
                    f"command contract access raised {type(exc).__name__}: {exc}",
                ) from exc
            if (
                type(name) is not str
                or _PLUGIN_NAME_PATTERN.fullmatch(name) is None
                or type(summary) is not str
                or not summary
                or not callable(configure_parser)
                or not callable(run)
            ):
                raise PluginLoadError(
                    plugin.name,
                    "command factory values must provide canonical name, non-empty "
                    "summary and callable configure_parser and run methods",
                )
            commands.append(
                _CapturedCliCommand(
                    plugin_name=plugin.name,
                    name=name,
                    summary=summary,
                    _configure_parser=cast(
                        Callable[[argparse.ArgumentParser], None],
                        configure_parser,
                    ),
                    _run=cast(
                        Callable[[argparse.Namespace, CliContext], object],
                        run,
                    ),
                )
            )
        return tuple(commands)


def default_plugin_state_path() -> Path:
    """Return the platform-local plugin activation-state path."""
    override = os.environ.get("OBST_CONFIG_HOME")
    if override:
        return Path(override) / "plugins.json"
    if os.name == "nt":
        root = os.environ.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Roaming"
        return base / "obst" / "plugins.json"
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / "obst" / "plugins.json"


def _index_entry_points(
    entry_points: tuple[metadata.EntryPoint, ...],
    group: str,
) -> dict[str, metadata.EntryPoint]:
    indexed: dict[str, metadata.EntryPoint] = {}
    for entry_point in entry_points:
        if entry_point.group != group:
            continue
        _validate_plugin_name(entry_point.name)
        if entry_point.name in indexed:
            raise PluginDiscoveryError(
                entry_point.name,
                f"duplicate entry-point name in group {group}",
            )
        indexed[entry_point.name] = entry_point
    return indexed


def _require_same_distribution(
    name: str,
    entries: tuple[metadata.EntryPoint, ...],
) -> None:
    if len(entries) < 2:
        return
    distributions = tuple(entry.dist for entry in entries)
    if any(distribution is None for distribution in distributions):
        raise PluginDiscoveryError(
            name,
            "plugin contributions have ambiguous distribution ownership",
        )
    owner = distributions[0]
    if any(distribution is not owner for distribution in distributions[1:]):
        raise PluginDiscoveryError(
            name,
            "plugin contributions come from different distributions",
        )


def _load_factory(
    plugin_name: str,
    entry_point: metadata.EntryPoint,
    *,
    error_factory: Callable[[str, str], PluginError],
) -> tuple[object, ...]:
    try:
        factory = entry_point.load()
    except Exception as exc:
        raise error_factory(
            plugin_name,
            f"entry point raised {type(exc).__name__}: {exc}",
        ) from exc
    if not callable(factory):
        raise error_factory(plugin_name, "entry point must resolve to a callable")
    try:
        values = factory()
    except Exception as exc:
        raise error_factory(
            plugin_name,
            f"factory raised {type(exc).__name__}: {exc}",
        ) from exc
    if type(values) is not tuple or not values:
        raise error_factory(
            plugin_name,
            "factory must return a non-empty exact tuple",
        )
    return cast(tuple[object, ...], values)


def _load_conformance_suite(
    plugin_name: str,
    entry_point: metadata.EntryPoint,
) -> ConformanceSuite:
    try:
        factory = entry_point.load()
    except Exception as exc:
        raise PluginConformanceError(
            plugin_name,
            f"entry point raised {type(exc).__name__}: {exc}",
        ) from exc
    if not callable(factory):
        raise PluginConformanceError(
            plugin_name, "entry point must resolve to a callable"
        )
    try:
        suite = factory()
    except Exception as exc:
        raise PluginConformanceError(
            plugin_name,
            f"factory raised {type(exc).__name__}: {exc}",
        ) from exc
    if type(suite) is not ConformanceSuite:
        raise PluginConformanceError(
            plugin_name,
            "factory must return one exact ConformanceSuite",
        )
    return suite


def _validate_plugin_name(name: object) -> None:
    if type(name) is not str or _PLUGIN_NAME_PATTERN.fullmatch(name) is None:
        raise PluginDiscoveryError(
            str(name),
            "name must be 1..128 lowercase ASCII letters, digits, '.', '_' or '-'",
        )


def _read_enabled_plugins(
    state_path: Path,
    default_enabled: frozenset[str],
) -> frozenset[str]:
    try:
        loaded: object = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_enabled
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginStateError(
            state_path,
            f"cannot read valid JSON: {type(exc).__name__}: {exc}",
        ) from exc
    if type(loaded) is not dict:
        raise PluginStateError(state_path, "document must be a JSON object")
    document = cast(dict[str, object], loaded)
    if set(document) != {"schema_version", "enabled"}:
        raise PluginStateError(
            state_path,
            "document must contain exactly schema_version and enabled",
        )
    if (
        type(document["schema_version"]) is not int
        or document["schema_version"] != PLUGIN_STATE_SCHEMA_VERSION
    ):
        raise PluginStateError(state_path, "unsupported plugin-state schema version")
    loaded_enabled = document["enabled"]
    if type(loaded_enabled) is not list:
        raise PluginStateError(state_path, "enabled must be a JSON array")
    enabled = cast(list[object], loaded_enabled)
    names: set[str] = set()
    for value in enabled:
        try:
            _validate_plugin_name(value)
        except PluginDiscoveryError as exc:
            raise PluginStateError(state_path, exc.reason) from exc
        name = cast(str, value)
        if name in names:
            raise PluginStateError(state_path, f"duplicate enabled plugin {name}")
        names.add(name)
    if enabled != sorted(names):
        raise PluginStateError(state_path, "enabled names must be sorted")
    return frozenset(names)


def _write_enabled_plugins(state_path: Path, enabled: frozenset[str]) -> None:
    document = {
        "schema_version": PLUGIN_STATE_SCHEMA_VERSION,
        "enabled": sorted(enabled),
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=state_path.parent,
            prefix=f".{state_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(document, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, state_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as exc:
        raise PluginStateError(
            state_path,
            f"cannot persist state: {type(exc).__name__}: {exc}",
        ) from exc


def _describe_distribution(
    distribution: metadata.Distribution | None,
) -> tuple[str | None, str | None]:
    if distribution is None:
        return None, None
    package_metadata = distribution.metadata
    summary = package_metadata.get("Summary") or None
    project_urls = package_metadata.get_all("Project-URL") or []
    documentation_url = next(
        (
            url.strip()
            for value in project_urls
            for label, separator, url in (value.partition(","),)
            if separator and label.strip().casefold() == "documentation" and url.strip()
        ),
        None,
    )
    return summary, documentation_url


__all__ = [
    "COMMAND_ENTRY_POINT_GROUP",
    "CONFORMANCE_ENTRY_POINT_GROUP",
    "EXTENSION_ENTRY_POINT_GROUP",
    "PLUGIN_STATE_SCHEMA_VERSION",
    "PluginConformanceError",
    "PluginDiscoveryError",
    "PluginError",
    "PluginLoadError",
    "PluginManager",
    "PluginRuntime",
    "PluginStateError",
    "PluginStatus",
    "default_plugin_state_path",
]
