from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
import zlib as stdlib_zlib
from importlib import metadata
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from obst.cli.commands import EXIT_SUCCESS
from obst.core import (
    ContainerReader,
    CoreResource,
    PipelineError,
    Recipe,
    ResourceAccounting,
    ResourceLimitError,
    StageCapability,
    StageSpec,
    decode_recipe,
    encode_recipe,
    inspect_container,
    iter_decoded_chunks,
)
from obst.plugins import (
    COMMAND_ENTRY_POINT_GROUP,
    CONFORMANCE_ENTRY_POINT_GROUP,
    EXTENSION_ENTRY_POINT_GROUP,
    PluginManager,
)
from obst.resources import LimitProfile, ResourceKind, ResourcePolicy

PLUGIN_ROOT = Path(__file__).parents[1]
ROOT = PLUGIN_ROOT.parents[1]
PLUGIN_SOURCE = PLUGIN_ROOT / "src"
PLUGIN_COMPARISON = PLUGIN_ROOT / "compare_samples.py"


def _accounting(
    *overrides: tuple[ResourceKind, int | None],
) -> ResourceAccounting:
    return ResourceAccounting(
        ResourcePolicy(
            tuple(CoreResource),
            LimitProfile(
                "test",
                "Test-only resource ceilings.",
                overrides,
            ),
        )
    )


def test_example_plugin_uses_only_public_obst_import_boundaries() -> None:
    imported_obst_modules: set[str] = set()
    source_paths = (
        *sorted((PLUGIN_ROOT / "src").rglob("*.py")),
        PLUGIN_COMPARISON,
    )
    for path in source_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path)
        imported_obst_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("obst")
            and not node.module.startswith("obst_example_adaptive_zlib")
        )

    assert imported_obst_modules == {
        "obst.cli",
        "obst.cli.commands",
        "obst.conformance",
        "obst.core",
    }


def test_example_plugin_entry_point_loads_and_round_trips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tomllib.loads(
        (PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    extension_target = project["project"]["entry-points"][EXTENSION_ENTRY_POINT_GROUP][
        "adaptive-zlib"
    ]
    conformance_target = project["project"]["entry-points"][
        CONFORMANCE_ENTRY_POINT_GROUP
    ]["adaptive-zlib"]
    command_target = project["project"]["entry-points"][COMMAND_ENTRY_POINT_GROUP][
        "adaptive-zlib"
    ]
    monkeypatch.setattr(sys, "path", [str(PLUGIN_SOURCE), *sys.path])
    extension_entry = metadata.EntryPoint(
        name="adaptive-zlib",
        value=extension_target,
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    conformance_entry = metadata.EntryPoint(
        name="adaptive-zlib",
        value=conformance_target,
        group=CONFORMANCE_ENTRY_POINT_GROUP,
    )
    command_entry = metadata.EntryPoint(
        name="adaptive-zlib",
        value=command_target,
        group=COMMAND_ENTRY_POINT_GROUP,
    )

    owner = next(iter(metadata.distributions()))
    for entry in (extension_entry, conformance_entry, command_entry):
        cast(Any, entry)._for(owner)
    all_entries = (command_entry, extension_entry, conformance_entry)

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        return tuple(
            entry for entry in all_entries if group is None or entry.group == group
        )

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)
    manager = PluginManager.discover(state_path=tmp_path / "plugins.json")
    manager.enable("adaptive-zlib")

    runtime = manager.runtime()
    registry = runtime.registry
    assert tuple(command.name for command in manager.commands()) == ("adaptive-pack",)
    stage_id = "org.example/adaptive-zlib@1"
    parameters = b"\x09\x07\x00"
    recipe = Recipe(0, (StageSpec(stage_id, parameters),))
    logical = b"".join(
        index.to_bytes(4, "little") + (1_000_000 + index * 3).to_bytes(4, "little")
        for index in range(8192)
    )

    assert registry.can_encode(stage_id)
    assert registry.can_decode(stage_id)
    encoded = encode_recipe(logical, recipe, registry, accounting=_accounting())
    assert encoded[:2] == b"\x03\x00"
    assert len(encoded) < len(stdlib_zlib.compress(logical, 9))
    assert (
        decode_recipe(
            encoded,
            recipe,
            registry,
            expected_size=len(logical),
            accounting=_accounting(),
        )
        == logical
    )
    capability = registry.capabilities()[0]
    assert isinstance(capability, StageCapability)
    assert capability.parameter_encoder_available
    assert capability.parameter_decoder_available
    assert capability.parameter_interpreter_available
    assert manager.test("adaptive-zlib").passed is True

    dictionary = b"sensor:value="
    dictionary_parameters = (
        b"\x06\x00\x01" + len(dictionary).to_bytes(2, "big") + dictionary
    )
    dictionary_recipe = Recipe(
        1,
        (StageSpec(stage_id, dictionary_parameters),),
    )
    dictionary_logical = b"sensor:value=100\nsensor:value=101\n"
    dictionary_encoded = encode_recipe(
        dictionary_logical, dictionary_recipe, registry, accounting=_accounting()
    )
    assert dictionary_encoded[:2] == b"\x00\x01"
    assert (
        decode_recipe(
            dictionary_encoded,
            dictionary_recipe,
            registry,
            expected_size=len(dictionary_logical),
            accounting=_accounting(),
        )
        == dictionary_logical
    )

    with pytest.raises(PipelineError, match="3-byte header"):
        encode_recipe(
            b"payload",
            Recipe(2, (StageSpec(stage_id, b"\x06"),)),
            registry,
            accounting=_accounting(),
        )
    with pytest.raises(PipelineError, match="undeclared shuffle mode"):
        decode_recipe(
            b"\xff\x00invalid",
            recipe,
            registry,
            expected_size=7,
            accounting=_accounting(),
        )
    with pytest.raises(ResourceLimitError):
        encode_recipe(
            b"small",
            recipe,
            registry,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 5)),
        )


def test_example_plugin_command_composes_another_plugins_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    adaptive_project = tomllib.loads(
        (PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    defaults_root = ROOT / "plugins" / "defaults"
    defaults_project = tomllib.loads(
        (defaults_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    adaptive_extension = metadata.EntryPoint(
        name="adaptive-zlib",
        value=adaptive_project["project"]["entry-points"][EXTENSION_ENTRY_POINT_GROUP][
            "adaptive-zlib"
        ],
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    adaptive_command = metadata.EntryPoint(
        name="adaptive-zlib",
        value=adaptive_project["project"]["entry-points"][COMMAND_ENTRY_POINT_GROUP][
            "adaptive-zlib"
        ],
        group=COMMAND_ENTRY_POINT_GROUP,
    )
    adaptive_conformance = metadata.EntryPoint(
        name="adaptive-zlib",
        value=adaptive_project["project"]["entry-points"][
            CONFORMANCE_ENTRY_POINT_GROUP
        ]["adaptive-zlib"],
        group=CONFORMANCE_ENTRY_POINT_GROUP,
    )
    defaults_extension = metadata.EntryPoint(
        name="obst-defaults",
        value=defaults_project["project"]["entry-points"][EXTENSION_ENTRY_POINT_GROUP][
            "obst-defaults"
        ],
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    defaults_command = metadata.EntryPoint(
        name="obst-defaults",
        value=defaults_project["project"]["entry-points"][COMMAND_ENTRY_POINT_GROUP][
            "obst-defaults"
        ],
        group=COMMAND_ENTRY_POINT_GROUP,
    )
    defaults_conformance = metadata.EntryPoint(
        name="obst-defaults",
        value=defaults_project["project"]["entry-points"][
            CONFORMANCE_ENTRY_POINT_GROUP
        ]["obst-defaults"],
        group=CONFORMANCE_ENTRY_POINT_GROUP,
    )
    entries = {
        EXTENSION_ENTRY_POINT_GROUP: (adaptive_extension, defaults_extension),
        COMMAND_ENTRY_POINT_GROUP: (adaptive_command, defaults_command),
        CONFORMANCE_ENTRY_POINT_GROUP: (
            adaptive_conformance,
            defaults_conformance,
        ),
    }
    owner = next(iter(metadata.distributions()))
    for entry in (
        *entries[EXTENSION_ENTRY_POINT_GROUP],
        *entries[COMMAND_ENTRY_POINT_GROUP],
        *entries[CONFORMANCE_ENTRY_POINT_GROUP],
    ):
        cast(Any, entry)._for(owner)
    all_entries = tuple(entry for group in entries.values() for entry in group)

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        return tuple(
            entry for entry in all_entries if group is None or entry.group == group
        )

    monkeypatch.setattr(
        metadata,
        "entry_points",
        installed_entry_points,
    )
    monkeypatch.setattr(sys, "path", [str(PLUGIN_SOURCE), *sys.path])
    manager = PluginManager.discover(state_path=tmp_path / "plugins.json")
    assert manager.commands() == ()
    manager.enable("adaptive-zlib")
    monkeypatch.setattr("obst.cli.main._plugin_manager", lambda: manager)
    from obst.cli.main import main

    logical = b"".join(index.to_bytes(8, "little") for index in range(16_384))
    source = tmp_path / "records.bin"
    source.write_bytes(logical)
    output = tmp_path / "records.obst"

    assert (
        main(
            [
                "adaptive-pack",
                str(source),
                "-o",
                str(output),
            ]
        )
        == EXIT_SUCCESS
    )
    rendered = capsys.readouterr().out
    assert "Adaptive pack complete" in rendered
    assert "Logical size    128.0 KiB" in rendered
    assert "Chunks          2" in rendered

    json_output = tmp_path / "records-json.obst"
    assert (
        main(
            [
                "adaptive-pack",
                str(source),
                "-o",
                str(json_output),
                "--json",
            ]
        )
        == EXIT_SUCCESS
    )
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "schema_version": 1,
        "destination": str(json_output),
        "logical_size": len(logical),
        "container_size": json_output.stat().st_size,
        "chunks": 2,
    }
    registry = manager.runtime().registry
    reader = ContainerReader(BytesIO(output.read_bytes()), accounting=_accounting())
    inspection = inspect_container(reader, registry=registry)
    assert inspection.chunk_count == 2
    assert tuple(stage.stage_id for stage in inspection.manifest.recipes[0].stages) == (
        "org.example/adaptive-zlib@1",
    )
    recovery_reader = ContainerReader(
        BytesIO(output.read_bytes()), accounting=_accounting()
    )
    recovered = b"".join(
        logical_chunk
        for _chunk, logical_chunk in iter_decoded_chunks(recovery_reader, registry)
    )
    assert recovered == logical


def test_example_plugin_round_trips_existing_obst_sample(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tomllib.loads(
        (PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    extension_target = project["project"]["entry-points"][EXTENSION_ENTRY_POINT_GROUP][
        "adaptive-zlib"
    ]
    monkeypatch.setattr(sys, "path", [str(PLUGIN_SOURCE), *sys.path])
    extension_entry = metadata.EntryPoint(
        name="adaptive-zlib",
        value=extension_target,
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    conformance_entry = metadata.EntryPoint(
        name="adaptive-zlib",
        value=project["project"]["entry-points"][CONFORMANCE_ENTRY_POINT_GROUP][
            "adaptive-zlib"
        ],
        group=CONFORMANCE_ENTRY_POINT_GROUP,
    )
    owner = next(iter(metadata.distributions()))
    for entry in (extension_entry, conformance_entry):
        cast(Any, entry)._for(owner)

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        if group is None:
            return extension_entry, conformance_entry
        if group == EXTENSION_ENTRY_POINT_GROUP:
            return (extension_entry,)
        if group == CONFORMANCE_ENTRY_POINT_GROUP:
            return (conformance_entry,)
        return ()

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)
    registry = (
        PluginManager.discover(state_path=tmp_path / "plugins.json")
        .runtime(("adaptive-zlib",))
        .registry
    )
    recipe = Recipe(
        0,
        (StageSpec("org.example/adaptive-zlib@1", b"\x09\x07\x00"),),
    )
    logical = (ROOT / "samples" / "apple.obst").read_bytes()[: 64 * 1024]

    encoded = encode_recipe(logical, recipe, registry, accounting=_accounting())

    assert encoded[:2] == b"\x00\x00"
    assert (
        decode_recipe(
            encoded,
            recipe,
            registry,
            expected_size=len(logical),
            accounting=_accounting(),
        )
        == logical
    )


def test_example_plugin_comparison_runs_from_unrelated_working_directory(
    tmp_path: Path,
) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(PLUGIN_SOURCE), str(ROOT / "src")))

    completed = subprocess.run(
        [sys.executable, PLUGIN_COMPARISON],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Synthetic fixed-width records" in completed.stdout
    assert "Existing samples/all-fruit.obst as ordinary bytes" in completed.stdout
    assert completed.stdout.count("Choices:") == 2
    assert completed.stdout.count("Round trip identical:   True") == 2
    assert not tuple(tmp_path.iterdir())
