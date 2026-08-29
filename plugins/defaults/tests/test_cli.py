# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import argparse
import io
import json
import struct
import subprocess
import sys
import zlib
from email.message import Message
from importlib import metadata
from pathlib import Path
from typing import Any, Self, cast

import pytest
from obst.cli import CliCommandError, CliContext
from obst.cli.commands import (
    EXIT_INVALID_CONTAINER,
    EXIT_IO,
    EXIT_PLUGIN,
    EXIT_RESOURCE_LIMIT,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
)
from obst.cli.main import main
from obst.conformance import ConformanceSuite, StageKnownAnswerCase
from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerWriter,
    CoreResource,
    Extension,
    ExtensionDeclaration,
    ExtensionDescriptor,
    ExtensionRegistry,
    Manifest,
    Recipe,
    ResourceLimitError,
    StageExtension,
    StageSpec,
    Stream,
    TruncatedContainerError,
    encode_chunk_once,
    format_version,
    require_no_parameters,
)
from obst.core.extensions import ExtensionKind
from obst.core.wire import ContainerHeader
from obst.plugins import (
    COMMAND_ENTRY_POINT_GROUP,
    CONFORMANCE_ENTRY_POINT_GROUP,
    EXTENSION_ENTRY_POINT_GROUP,
    RESOURCE_ENTRY_POINT_GROUP,
)

from obst_defaults.carriers import CarrierError
from obst_defaults.carriers.filesystem import FilesystemCarrierExtension
from obst_defaults.codecs.zlib import (
    ZlibDictionaryExtension,
    ZlibDictionaryParameters,
    ZlibExtension,
)
from obst_defaults.commands import (
    _has_windows_origin_mark,  # pyright: ignore[reportPrivateUsage]
)
from obst_defaults.commands import _unpack_path  # pyright: ignore[reportPrivateUsage]
from obst_defaults.commands import (
    EXIT_ARCHIVE,
    EXIT_CARRIER,
)
from obst_defaults.files import FileExtension, FileResource
from support_resources import accounting as _accounting

_FIRST_PARTY_PLUGIN_NAME = "obst-defaults"
_FIRST_PARTY_PLUGIN_TARGET = "obst_defaults.bundle:obst_extensions"
_FIRST_PARTY_COMMAND_TARGET = "obst_defaults.commands:obst_commands"
_FIRST_PARTY_CONFORMANCE_TARGET = "obst_defaults.conformance:obst_conformance"
_FIRST_PARTY_RESOURCE_TARGET = "obst_defaults.bundle:obst_resources"


class _StubDistribution:
    def __init__(self, name: str) -> None:
        package_metadata = Message()
        package_metadata["Name"] = name
        package_metadata["Version"] = "1.0"
        self.name = name
        self.version = "1.0"
        self.metadata = cast(metadata.PackageMetadata, package_metadata)


class _FailingCloseReaderSession:
    def open(self) -> io.BytesIO:
        return io.BytesIO()

    def close(self) -> None:
        raise CarrierError("reader close failed")


class _ReaderOnlyFilesystemExtension:
    extension_id = "obst.filesystem@1"
    descriptor = FilesystemCarrierExtension.descriptor
    kind = ExtensionKind.CARRIER

    def __init__(self, session: _FailingCloseReaderSession) -> None:
        self._session = session

    def bind_reader(self, request: object, /) -> _FailingCloseReaderSession:
        return self._session


def _first_party_plugin() -> metadata.EntryPoint:
    return metadata.EntryPoint(
        name=_FIRST_PARTY_PLUGIN_NAME,
        value=_FIRST_PARTY_PLUGIN_TARGET,
        group=EXTENSION_ENTRY_POINT_GROUP,
    )


def _first_party_commands() -> metadata.EntryPoint:
    return metadata.EntryPoint(
        name=_FIRST_PARTY_PLUGIN_NAME,
        value=_FIRST_PARTY_COMMAND_TARGET,
        group=COMMAND_ENTRY_POINT_GROUP,
    )


def _first_party_resources() -> metadata.EntryPoint:
    return metadata.EntryPoint(
        name=_FIRST_PARTY_PLUGIN_NAME,
        value=_FIRST_PARTY_RESOURCE_TARGET,
        group=RESOURCE_ENTRY_POINT_GROUP,
    )


def _conformance_entry(name: str) -> metadata.EntryPoint:
    target = (
        _FIRST_PARTY_CONFORMANCE_TARGET
        if name == _FIRST_PARTY_PLUGIN_NAME
        else f"{__name__}:cli_conformance_factory"
    )
    return metadata.EntryPoint(
        name=name,
        value=target,
        group=CONFORMANCE_ENTRY_POINT_GROUP,
    )


def _install_plugin_entries(
    monkeypatch: pytest.MonkeyPatch,
    extensions: tuple[metadata.EntryPoint, ...],
    conformance: tuple[metadata.EntryPoint, ...] = (),
    commands: tuple[metadata.EntryPoint, ...] | None = None,
) -> None:
    explicit_conformance_names = {entry.name for entry in conformance}
    conformance = conformance + tuple(
        _conformance_entry(entry.name)
        for entry in extensions
        if entry.name not in explicit_conformance_names
    )
    command_entries = (
        (
            (_first_party_commands(),)
            if any(entry.name == _FIRST_PARTY_PLUGIN_NAME for entry in extensions)
            else ()
        )
        if commands is None
        else commands
    )
    resource_entries = (
        (_first_party_resources(),)
        if any(entry.name == _FIRST_PARTY_PLUGIN_NAME for entry in extensions)
        else ()
    )
    entries = {
        EXTENSION_ENTRY_POINT_GROUP: extensions,
        COMMAND_ENTRY_POINT_GROUP: command_entries,
        CONFORMANCE_ENTRY_POINT_GROUP: conformance,
        RESOURCE_ENTRY_POINT_GROUP: resource_entries,
    }
    all_entries = extensions + command_entries + conformance + resource_entries
    entries_by_name: dict[str, list[metadata.EntryPoint]] = {}
    for entry in all_entries:
        entries_by_name.setdefault(entry.name, []).append(entry)
    for name, owned_entries in entries_by_name.items():
        if len(owned_entries) > 1 and all(
            entry.dist is None for entry in owned_entries
        ):
            owner = _StubDistribution(name)
            for entry in owned_entries:
                cast(Any, entry)._for(owner)

    def installed_entry_points(**params: str) -> tuple[metadata.EntryPoint, ...]:
        group = params.get("group")
        if group is None:
            return all_entries
        return entries[group]

    monkeypatch.setattr(metadata, "entry_points", installed_entry_points)


@pytest.fixture(autouse=True)
def isolated_plugin_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_home = tmp_path / "config"
    monkeypatch.setenv("OBST_CONFIG_HOME", str(config_home))
    config_home.mkdir()
    (config_home / "plugins.json").write_text(
        '{"enabled": ["obst-defaults"], "schema_version": 1}\n',
        encoding="utf-8",
    )
    _install_plugin_entries(monkeypatch, (_first_party_plugin(),))


def _manifest(
    *,
    stage_id: str | None = None,
    specification_url: str | None = None,
) -> Manifest:
    extensions = (
        ()
        if stage_id is None or specification_url is None
        else (ExtensionDeclaration(stage_id, specification_url),)
    )
    return Manifest(
        recipes=(Recipe(0, () if stage_id is None else (StageSpec(stage_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
        extensions=extensions,
    )


def _container(
    payload: bytes = b"payload",
    *,
    codec: _ExplodingDecodeExtension | None = None,
) -> bytes:
    extensions: list[StageExtension] = []
    stage_id = None
    specification_url = None
    if codec is not None:
        extensions.append(codec)
        stage_id = codec.extension_id
        specification_url = codec.descriptor.specification_url
    registry = ExtensionRegistry(extensions)
    target = io.BytesIO()
    manifest = _manifest(stage_id=stage_id, specification_url=specification_url)
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            payload,
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.finish()
    return target.getvalue()


def _write_container(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "sample.obst"
    path.write_bytes(data)
    return path


def _zlib_dictionary_container(payload: bytes) -> bytes:
    extension = ZlibDictionaryExtension()
    registry = ExtensionRegistry((extension,))
    parameters = extension.encode_parameters(
        ZlibDictionaryParameters(9, b"common-prefix:")
    )
    manifest = Manifest(
        recipes=(
            Recipe(
                0,
                (StageSpec(ZlibDictionaryExtension.extension_id, parameters),),
            ),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            payload,
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.finish()
    return target.getvalue()


def test_inspect_command_writes_the_human_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_container(tmp_path, _container())

    exit_code = main(["inspect", str(path)])
    captured = capsys.readouterr()

    assert exit_code == EXIT_SUCCESS
    assert f"OBST container {format_version.label}" in captured.out
    assert "Stage capabilities" in captured.out
    assert captured.err == ""


def test_inspect_is_available_without_any_enabled_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "config" / "plugins.json").write_text(
        '{"enabled": [], "schema_version": 1}\n',
        encoding="utf-8",
    )
    _install_plugin_entries(monkeypatch, ())
    path = _write_container(tmp_path, _container())

    assert main(["inspect", str(path), "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)

    assert document["required_decoders_available"] is True
    assert document["missing_required_stages"] == []


def test_inspect_reports_zlib_v2_decoder_as_available(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_container(
        tmp_path,
        _zlib_dictionary_container(b"common-prefix:value"),
    )

    exit_code = main(["inspect", str(path), "--json"])
    captured = capsys.readouterr()
    document = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert document["missing_required_stages"] == []
    assert document["stage_details"][0]["id"] == ZlibDictionaryExtension.extension_id
    assert document["stage_details"][0]["decoder_available"] is True
    assert (
        document["recipe_details"][0]["stages"][0]["parameters_interpretation"]
        is not None
    )
    assert (
        ZlibDictionaryExtension.extension_id
        in document["interpretation_policy"]["extension_ids"]
    )
    assert captured.err == ""


def test_structural_inspection_skips_interpreters(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_container(
        tmp_path,
        _zlib_dictionary_container(b"common-prefix:value"),
    )

    exit_code = main(["inspect", str(path), "--json", "--structural"])
    document = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert document["interpretation_policy"] == {"extension_ids": []}
    assert (
        document["recipe_details"][0]["stages"][0]["parameters_interpretation"] is None
    )
    assert document["stage_details"][0]["decoder_available"] is True


def test_inspect_reads_a_non_seekable_stdin_pipe() -> None:
    encoded = _container()

    completed = subprocess.run(
        [sys.executable, "-m", "obst.cli", "inspect", "-", "--json"],
        input=encoded,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == EXIT_SUCCESS
    assert json.loads(completed.stdout)["container_size"] == len(encoded)
    assert completed.stderr == b""


def test_human_output_is_utf8_when_stdout_is_redirected(tmp_path: Path) -> None:
    path = _write_container(tmp_path, _container())

    completed = subprocess.run(
        [sys.executable, "-m", "obst.cli", "inspect", str(path)],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == EXIT_SUCCESS
    assert "███████" in completed.stdout.decode("utf-8")
    assert completed.stderr == b""


def test_pack_and_unpack_commands_preserve_selected_filenames(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    apple = tmp_path / "apple.txt"
    banana = tmp_path / "banana.bin"
    apple.write_text("red", encoding="utf-8")
    banana.write_bytes(bytes(range(64)))
    archive = tmp_path / "fruit.obst"

    assert main(["pack", str(apple), str(banana), "-o", str(archive)]) == EXIT_SUCCESS
    packed = capsys.readouterr()
    assert "Packed 2 files" in packed.out
    assert "apple.txt" in packed.out
    assert "banana.bin" in packed.out
    assert packed.err == ""

    output = tmp_path / "output"
    assert main(["unpack", str(archive), "-o", str(output)]) == EXIT_SUCCESS
    unpacked = capsys.readouterr()
    assert "Unpacked 2 files" in unpacked.out
    assert (output / "apple.txt").read_text(encoding="utf-8") == "red"
    assert (output / "banana.bin").read_bytes() == bytes(range(64))
    assert unpacked.err == ""


def test_pack_and_unpack_commands_emit_stable_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "apple.txt"
    source.write_text("red", encoding="utf-8")
    archive = tmp_path / "fruit.obst"

    assert main(["pack", str(source), "-o", str(archive), "--json"]) == EXIT_SUCCESS
    packed = capsys.readouterr()
    packed_document = json.loads(packed.out)
    assert packed_document == {
        "schema_version": 1,
        "destination": str(archive),
        "container_size": archive.stat().st_size,
        "files": [
            {
                "name": "apple.txt",
                "logical_size": 3,
                "chunks": 1,
            }
        ],
        "cleanup_issues": [],
    }
    assert packed.err == ""

    output = tmp_path / "output"
    assert main(["unpack", str(archive), "-o", str(output), "--json"]) == EXIT_SUCCESS
    unpacked = capsys.readouterr()
    assert json.loads(unpacked.out) == {
        "schema_version": 1,
        "destination": str(output),
        "files": [
            {
                "name": "apple.txt",
                "path": str(output / "apple.txt"),
            }
        ],
        "cleanup_issues": [],
        "windows_origin_not_propagated": False,
    }
    assert unpacked.err == ""
    assert (output / "apple.txt").read_text(encoding="utf-8") == "red"


def test_active_custom_profile_limits_pack_and_unpack_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "apple.txt"
    source.write_text("red", encoding="utf-8")
    archive = tmp_path / "fruit.obst"
    assert main(["pack", str(source), "-o", str(archive)]) == EXIT_SUCCESS
    capsys.readouterr()

    assert main(["limits", "create", "tiny"]) == EXIT_SUCCESS
    capsys.readouterr()
    assert (
        main(
            [
                "limits",
                "set",
                "tiny",
                str(FileResource.ARCHIVE_MEMBERS),
                "0",
            ]
        )
        == EXIT_SUCCESS
    )
    capsys.readouterr()
    assert main(["limits", "use", "tiny"]) == EXIT_SUCCESS
    capsys.readouterr()

    assert (
        main(["unpack", str(archive), "-o", str(tmp_path / "output")])
        == EXIT_RESOURCE_LIMIT
    )
    assert str(FileResource.ARCHIVE_MEMBERS) in capsys.readouterr().err

    assert (
        main(
            [
                "limits",
                "set",
                "tiny",
                str(CoreResource.STREAMS),
                "0",
            ]
        )
        == EXIT_SUCCESS
    )
    capsys.readouterr()
    assert (
        main(["pack", str(source), "-o", str(tmp_path / "blocked.obst")])
        == EXIT_RESOURCE_LIMIT
    )
    assert str(CoreResource.STREAMS) in capsys.readouterr().err


def test_enabling_resource_plugin_does_not_select_its_profiles(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["limits", "profiles", "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)

    active = [profile for profile in document["profiles"] if profile["active"]]
    assert [profile["id"] for profile in active] == ["default"]


def test_unpack_accepts_nonempty_directory_without_member_collisions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "apple.txt"
    source.write_text("red", encoding="utf-8")
    archive = tmp_path / "fruit.obst"
    assert main(["pack", str(source), "-o", str(archive)]) == EXIT_SUCCESS
    capsys.readouterr()
    output = tmp_path / "output"
    output.mkdir()
    unrelated = output / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    assert main(["unpack", str(archive), "-o", str(output)]) == EXIT_SUCCESS

    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert (output / source.name).read_text(encoding="utf-8") == "red"


def test_unpack_warns_when_windows_origin_is_not_propagated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "apple.txt"
    source.write_text("red", encoding="utf-8")
    archive = tmp_path / "fruit.obst"
    assert main(["pack", str(source), "-o", str(archive)]) == EXIT_SUCCESS
    capsys.readouterr()

    def has_windows_origin_mark(path: Path) -> bool:
        assert path == archive
        return True

    monkeypatch.setattr(
        "obst_defaults.commands._has_windows_origin_mark",
        has_windows_origin_mark,
    )

    assert main(["unpack", str(archive), "-o", str(tmp_path / "output")]) == 0

    captured = capsys.readouterr()
    assert "input has Windows Mark of the Web" in captured.err


def test_unpack_preserves_container_failure_when_reader_close_also_fails(
    tmp_path: Path,
) -> None:
    session = _FailingCloseReaderSession()
    registry = ExtensionRegistry(
        (
            _ReaderOnlyFilesystemExtension(session),
            FileExtension(),
        )
    )
    context = CliContext(
        registry=registry,
        plugin_names=("test",),
        stdin=io.BytesIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        accounting=_accounting(),
    )

    with pytest.raises(TruncatedContainerError) as error:
        _unpack_path(
            context,
            input_path=str(tmp_path / "empty.obst"),
            output_directory=str(tmp_path / "output"),
        )

    assert error.value.__notes__ == [
        f"failed to close input carrier {tmp_path / 'empty.obst'}: reader close failed"
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data stream")
def test_windows_origin_detection_reads_zone_identifier(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    container = tmp_path / "download.obst"
    assert main(["pack", str(source), "-o", str(container)]) == EXIT_SUCCESS
    capsys.readouterr()
    try:
        Path(f"{container}:Zone.Identifier").write_text(
            "[ZoneTransfer]\nZoneId=3\n",
            encoding="ascii",
        )
    except OSError:
        pytest.skip("temporary filesystem does not support alternate data streams")

    assert (
        main(["unpack", str(container), "-o", str(tmp_path / "output")]) == EXIT_SUCCESS
    )
    assert "input has Windows Mark of the Web" in capsys.readouterr().err


@pytest.mark.parametrize("failure", (FileNotFoundError("missing"), OSError("denied")))
def test_windows_origin_detection_is_conservative_on_probe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: OSError,
) -> None:
    def fail_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("obst_defaults.commands.sys.platform", "win32")
    monkeypatch.setattr(Path, "open", fail_open)

    assert not _has_windows_origin_mark(tmp_path / "download.obst")


def test_pack_and_unpack_commands_pluralize_single_file_and_chunk(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "apple.txt"
    source.write_text("red", encoding="utf-8")
    archive = tmp_path / "fruit.obst"

    assert main(["pack", str(source), "-o", str(archive)]) == EXIT_SUCCESS
    packed = capsys.readouterr()
    assert "Packed 1 file" in packed.out
    assert "\n  Destination     " in packed.out
    assert "\n  Container size  " in packed.out
    assert "\n\nFiles\n  File" in packed.out
    assert "\n  apple.txt   3 B       1" in packed.out

    output = tmp_path / "output"
    assert main(["unpack", str(archive), "-o", str(output)]) == EXIT_SUCCESS
    unpacked = capsys.readouterr()
    assert "Unpacked 1 file" in unpacked.out
    assert "1 files" not in unpacked.out


def test_pack_and_unpack_work_through_process_cli(tmp_path: Path) -> None:
    apple = tmp_path / "apple.txt"
    banana = tmp_path / "banana.bin"
    apple.write_text("red", encoding="utf-8")
    banana.write_bytes(bytes(range(64)))
    archive = tmp_path / "fruit.obst"
    output = tmp_path / "output"

    packed = subprocess.run(
        [
            sys.executable,
            "-m",
            "obst.cli",
            "pack",
            str(apple),
            str(banana),
            "-o",
            str(archive),
        ],
        capture_output=True,
        check=False,
    )
    unpacked = subprocess.run(
        [
            sys.executable,
            "-m",
            "obst.cli",
            "unpack",
            str(archive),
            "-o",
            str(output),
        ],
        capture_output=True,
        check=False,
    )

    assert packed.returncode == EXIT_SUCCESS
    assert "Packed 2 files" in packed.stdout.decode("utf-8")
    assert packed.stderr == b""
    assert unpacked.returncode == EXIT_SUCCESS
    assert "Unpacked 2 files" in unpacked.stdout.decode("utf-8")
    assert unpacked.stderr == b""
    assert (output / "apple.txt").read_text(encoding="utf-8") == "red"
    assert (output / "banana.bin").read_bytes() == bytes(range(64))


def test_pack_help_names_inputs_and_output_explicitly() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "obst.cli", "pack", "--help"],
        capture_output=True,
        check=False,
    )

    output = completed.stdout.decode("utf-8")
    assert completed.returncode == EXIT_SUCCESS
    assert "-o OUTPUT" in output
    assert "INPUT [INPUT ...]" in output
    assert "Name the destination explicitly with -o/--output" in output
    assert "obst pack apple.jpg banana.jpg -o samples/fruits.obst" in output
    assert completed.stderr == b""


def test_unpack_help_names_input_and_output_directory_explicitly() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "obst.cli", "unpack", "--help"],
        capture_output=True,
        check=False,
    )

    output = completed.stdout.decode("utf-8")
    assert completed.returncode == EXIT_SUCCESS
    assert "-o OUTPUT_DIRECTORY" in output
    assert "INPUT" in output
    assert "Name the destination explicitly with -o/--output" in output
    assert "obst unpack fruits.obst -o restored" in output
    assert completed.stderr == b""


def test_plugin_test_help_warns_that_plugin_code_is_executed() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "obst.cli", "plugins", "test", "--help"],
        capture_output=True,
        check=False,
    )

    output = completed.stdout.decode("utf-8")
    assert completed.returncode == EXIT_SUCCESS
    assert "executes installed plugin code" in output
    assert "No sandbox is used" in output
    assert "Test only plugins you trust" in output
    assert completed.stderr == b""


def test_help_command_shows_general_and_command_specific_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["help"]) == EXIT_SUCCESS
    general = capsys.readouterr()
    assert "usage: obst" in general.out
    assert "help" in general.out
    assert "pack" in general.out
    assert "unpack" in general.out
    assert general.err == ""

    assert main(["help", "inspect"]) == EXIT_SUCCESS
    inspect_help = capsys.readouterr()
    assert "usage: obst inspect" in inspect_help.out
    assert "--require-decodable" in inspect_help.out
    assert inspect_help.err == ""


def test_empty_command_usage_lists_enabled_plugin_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as missing_command:
        main([])

    assert missing_command.value.code == EXIT_USAGE
    error = capsys.readouterr().err
    assert "pack" in error
    assert "unpack" in error


def test_empty_command_colors_plugin_commands_differently(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("PYTHON_COLORS", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")

    with pytest.raises(SystemExit) as missing_command:
        main([])

    assert missing_command.value.code == EXIT_USAGE
    error = capsys.readouterr().err
    assert "\x1b[32minspect\x1b[0m" in error
    assert "\x1b[35mpack\x1b[0m" in error
    assert "\x1b[35munpack\x1b[0m" in error


@pytest.mark.parametrize(
    "arguments",
    (
        ("pack", "output.obst", "input.bin"),
        ("unpack", "input.obst"),
    ),
)
def test_archive_commands_require_explicit_output(arguments: tuple[str, ...]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "obst.cli", *arguments],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == EXIT_USAGE
    assert (
        "the following arguments are required: -o/--output"
        in completed.stderr.decode("utf-8")
    )
    assert completed.stdout == b""


def test_unpack_command_reports_archive_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_container(tmp_path, _container())

    assert main(["unpack", str(path), "-o", str(tmp_path / "out")]) == EXIT_ARCHIVE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("obst: archive_error:")


def test_pack_command_reports_carrier_publication_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "apple.txt"
    source.write_text("red", encoding="utf-8")
    target = tmp_path / "fruit.obst"
    target.write_bytes(b"keep")

    assert main(["pack", str(source), "-o", str(target)]) == EXIT_CARRIER
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err.startswith("obst: carrier_error:")
    assert target.read_bytes() == b"keep"


def test_pack_command_reports_archiver_composition_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_and_target = tmp_path / "same.bin"
    source_and_target.write_bytes(b"keep")

    assert (
        main(
            [
                "pack",
                str(source_and_target),
                "-o",
                str(source_and_target),
            ]
        )
        == EXIT_ARCHIVE
    )
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err.startswith("obst: archive_error:")
    assert source_and_target.read_bytes() == b"keep"


def test_inspect_reports_missing_stage_without_decoding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_container(tmp_path, _container(codec=_ExplodingDecodeExtension()))

    exit_code = main(["inspect", str(path), "--json"])
    document = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert document["required_decoders_available"] is False
    assert document["missing_required_stages"] == [
        _ExplodingDecodeExtension.extension_id
    ]
    assert document["logical_recovery"] == "not_attempted"

    exit_code = main(["inspect", str(path), "--quiet", "--require-decodable"])
    captured = capsys.readouterr()
    assert exit_code == EXIT_UNSUPPORTED
    assert captured.out == ""
    assert captured.err == ""


def test_container_stage_ids_never_select_an_installed_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_container(tmp_path, _container(codec=_ExplodingDecodeExtension()))

    untrusted = metadata.EntryPoint(
        name="untrusted",
        value="module.that.must.not.load:factory",
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    _install_plugin_entries(monkeypatch, (_first_party_plugin(), untrusted))

    assert main(["inspect", str(path), "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    assert document["missing_required_stages"] == [
        _ExplodingDecodeExtension.extension_id
    ]


def test_plugins_command_lists_entry_points_without_loading_them(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plugin = metadata.EntryPoint(
        name="example",
        value="module.that.must.not.load:factory",
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    _install_plugin_entries(monkeypatch, (plugin,))

    assert main(["plugins", "list", "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    assert document["entry_point_groups"] == {
        "commands": COMMAND_ENTRY_POINT_GROUP,
        "extensions": EXTENSION_ENTRY_POINT_GROUP,
        "conformance": CONFORMANCE_ENTRY_POINT_GROUP,
        "resources": RESOURCE_ENTRY_POINT_GROUP,
    }
    assert document["schema_version"] == 6
    plugins = {item["name"]: item for item in document["plugins"]}
    assert plugins["example"] == {
        "conformance_reference": f"{__name__}:cli_conformance_factory",
        "command_reference": None,
        "distribution_name": "example",
        "distribution_version": "1.0",
        "documentation_url": None,
        "enabled": False,
        "extension_reference": "module.that.must.not.load:factory",
        "installed": True,
        "name": "example",
        "resource_reference": None,
        "summary": None,
    }
    assert plugins["obst-defaults"]["installed"] is False
    assert plugins["obst-defaults"]["enabled"] is True

    assert main(["plugins", "list"]) == EXIT_SUCCESS
    human = capsys.readouterr().out
    assert "Metadata only; plugin code was not loaded" in human
    assert "Installed       yes" in human
    assert "Enabled         no" in human
    assert "Default         " not in human
    assert "Extensions      module.that.must.not.load:factory" in human


def test_enabled_command_only_plugin_contributes_a_cli_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = metadata.EntryPoint(
        name="example-command-plugin",
        value=f"{__name__}:cli_command_factory",
        group=COMMAND_ENTRY_POINT_GROUP,
    )
    _install_plugin_entries(
        monkeypatch,
        (_first_party_plugin(),),
        commands=(command,),
    )

    assert main(["plugins", "enable", "example-command-plugin"]) == EXIT_SUCCESS
    capsys.readouterr()

    assert main(["example-command", "--value", "dynamic"]) == EXIT_SUCCESS
    captured = capsys.readouterr()
    assert captured.out == "dynamic\n"
    assert captured.err == ""


@pytest.mark.parametrize("exit_code", (True, -1, 256))
def test_cli_command_error_requires_a_portable_exact_exit_code(
    exit_code: object,
) -> None:
    with pytest.raises(ValueError, match=r"exact integer in 0\.\.255"):
        CliCommandError("plugin_error", exit_code, RuntimeError("failure"))  # type: ignore[arg-type]


def test_plugin_command_uses_one_captured_factory_result_with_one_shot_extensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    global _counting_command_factory_calls
    _counting_command_factory_calls = 0
    config_home = tmp_path / "config"
    config_home.mkdir(exist_ok=True)
    (config_home / "plugins.json").write_text(
        '{"enabled": ["snapshot"], "schema_version": 1}\n',
        encoding="utf-8",
    )
    command = metadata.EntryPoint(
        name="snapshot",
        value=f"{__name__}:counting_cli_command_factory",
        group=COMMAND_ENTRY_POINT_GROUP,
    )
    extension = metadata.EntryPoint(
        name="extra",
        value=f"{__name__}:cli_extension_factory",
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    _install_plugin_entries(monkeypatch, (extension,), commands=(command,))

    assert (
        main(["snapshot-command", "--plugin", "extra", "--value", "same"])
        == EXIT_SUCCESS
    )

    assert _counting_command_factory_calls == 1
    assert capsys.readouterr().out == "same\n"


def test_generic_version_and_builtin_help_do_not_load_plugin_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_home = tmp_path / "config"
    config_home.mkdir(exist_ok=True)
    (config_home / "plugins.json").write_text(
        '{"enabled": ["broken"], "schema_version": 1}\n',
        encoding="utf-8",
    )
    command = metadata.EntryPoint(
        name="broken",
        value=f"{__name__}:exploding_cli_command_factory",
        group=COMMAND_ENTRY_POINT_GROUP,
    )
    _install_plugin_entries(monkeypatch, (), commands=(command,))

    with pytest.raises(SystemExit) as version:
        main(["--version"])
    assert version.value.code == EXIT_SUCCESS
    assert "obst format" in capsys.readouterr().out

    assert main(["help", "inspect"]) == EXIT_SUCCESS
    assert "usage: obst inspect" in capsys.readouterr().out


def test_extensions_command_reports_builtin_capability_inventory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["extensions", "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    capabilities = {item["id"]: item for item in document["extensions"]}

    assert document["schema_version"] == 3
    assert "obst.raw@1" not in capabilities
    assert (
        capabilities[ZlibExtension.extension_id]["parameter_encoder_available"] is True
    )
    assert (
        capabilities[ZlibExtension.extension_id]["parameter_decoder_available"] is True
    )
    assert capabilities["obst.file@1"]["kind"] == "stream_profile"
    assert capabilities["obst.file@1"]["metadata_encoder_available"] is True
    assert capabilities["obst.file@1"]["metadata_decoder_available"] is True
    assert capabilities["obst.file@1"]["metadata_interpreter_available"] is True
    assert capabilities["obst.filesystem@1"]["kind"] == "carrier"
    assert capabilities["obst.filesystem@1"]["reader_available"] is True
    assert capabilities["obst.filesystem@1"]["publisher_available"] is True
    assert capabilities["obst.filesystem@1"]["specification_url"].endswith(
        "plugins/defaults/docs/carriers/filesystem.md"
    )
    assert capabilities["obst.memory@1"]["kind"] == "carrier"
    assert capabilities["obst.stdin@1"]["reader_available"] is True
    assert capabilities["obst.stdin@1"]["publisher_available"] is False
    assert capabilities["obst.fixed@1"] == {
        "display_name": "Fixed packager",
        "specification_url": (
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/packagers/fixed.md"
        ),
        "id": "obst.fixed@1",
        "kind": "packager",
        "provider_available": True,
        "summary": "Package each logical source once with its declared fixed recipe.",
    }


def test_human_extension_inventory_separates_capability_blocks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["extensions"]) == EXIT_SUCCESS
    captured = capsys.readouterr()

    assert "\n\nobst.file@1" in captured.out
    assert "\n\nobst.zlib@1" in captured.out
    assert "Parameters      encode yes, decode yes, interpret yes" in captured.out
    assert "Metadata        encode yes, decode yes, interpret yes" in captured.out
    assert "Carrier         read yes, write no, publish yes" in captured.out
    assert "Carrier         read yes, write no, publish no" in captured.out
    assert "Packager        prepare yes" in captured.out
    assert (
        "Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md"
        in captured.out
    )
    assert (
        "Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/filesystem.md"
        in captured.out
    )
    assert captured.err == ""


def test_explicit_plugin_selection_extends_inspection_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plugin = metadata.EntryPoint(
        name="example",
        value=f"{__name__}:cli_extension_factory",
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    path = _write_container(tmp_path, _container(codec=_ExplodingDecodeExtension()))
    _install_plugin_entries(monkeypatch, (_first_party_plugin(), plugin))

    assert main(["inspect", str(path), "--json", "--plugin", "example"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    assert document["required_decoders_available"] is True
    assert document["missing_required_stages"] == []
    assert document["logical_recovery"] == "not_attempted"


def test_unknown_plugin_name_maps_to_a_dedicated_cli_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_plugin_entries(monkeypatch, (_first_party_plugin(),))

    assert main(["extensions", "--plugin", "missing"]) == EXIT_PLUGIN
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("obst: plugin_error:")


def test_plugin_activation_and_conformance_commands_use_the_manager(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    example = metadata.EntryPoint(
        name="example",
        value=f"{__name__}:cli_conforming_extension_factory",
        group=EXTENSION_ENTRY_POINT_GROUP,
    )
    conformance = metadata.EntryPoint(
        name="example",
        value=f"{__name__}:cli_conformance_factory",
        group=CONFORMANCE_ENTRY_POINT_GROUP,
    )
    _install_plugin_entries(
        monkeypatch,
        (_first_party_plugin(), example),
        (conformance,),
    )

    assert main(["plugins", "enable", "example"]) == EXIT_SUCCESS
    assert capsys.readouterr().out == "Enabled plugin example\n"

    assert main(["extensions", "--json"]) == EXIT_SUCCESS
    inventory = json.loads(capsys.readouterr().out)
    assert _ConformingCliExtension.extension_id in {
        item["id"] for item in inventory["extensions"]
    }

    assert main(["plugins", "test", "example", "--json"]) == EXIT_SUCCESS
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == (
        "obst: warning: plugin conformance executes installed plugin code with "
        "your current process privileges. No sandbox is used. Test only plugins "
        "you trust.\n"
    )
    assert report["passed"] is True
    assert report["cases"] == [
        {
            "error": None,
            "extension_id": _ConformingCliExtension.extension_id,
            "id": "conforming-known-answer",
            "kind": "stage-known-answer",
            "passed": True,
        }
    ]

    assert main(["plugins", "disable", "example"]) == EXIT_SUCCESS
    assert capsys.readouterr().out == "Disabled plugin example\n"


def test_disabling_bundled_plugin_removes_its_capabilities_and_file_tools(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "input.txt"
    source.write_bytes(b"payload")

    assert main(["plugins", "disable", "obst-defaults"]) == EXIT_SUCCESS
    capsys.readouterr()

    assert main(["extensions", "--json"]) == EXIT_SUCCESS
    assert json.loads(capsys.readouterr().out)["extensions"] == []

    with pytest.raises(SystemExit) as missing_command:
        main(["pack", str(source), "-o", str(tmp_path / "without-obst.obst")])
    assert missing_command.value.code == EXIT_USAGE
    capsys.readouterr()

    assert main(["plugins", "enable", "obst-defaults"]) == EXIT_SUCCESS
    capsys.readouterr()
    enabled_output = tmp_path / "with-obst.obst"
    assert main(["pack", str(source), "-o", str(enabled_output)]) == EXIT_SUCCESS
    assert enabled_output.is_file()


def test_require_decodable_ignores_missing_stages_from_unused_recipes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codec = _ExplodingDecodeExtension()
    registry = ExtensionRegistry((codec,))
    manifest = Manifest(
        recipes=(
            Recipe(0, ()),
            Recipe(1, (StageSpec(_ExplodingDecodeExtension.extension_id),)),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            b"payload",
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.finish()
    path = _write_container(tmp_path, target.getvalue())

    assert main(["inspect", str(path), "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    assert document["required_decoders_available"] is True
    assert document["missing_required_stages"] == []
    assert document["missing_declared_stages"] == [
        _ExplodingDecodeExtension.extension_id
    ]

    assert (
        main(["inspect", str(path), "--quiet", "--require-decodable"]) == EXIT_SUCCESS
    )
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("data", "error_kind"),
    [
        (b"", "truncated_container"),
        (b"OBST", "truncated_container"),
        (_container()[:-1], "truncated_container"),
    ],
)
def test_inspect_maps_invalid_or_truncated_input_to_exit_three(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    data: bytes,
    error_kind: str,
) -> None:
    path = _write_container(tmp_path, data)

    assert main(["inspect", str(path), "--quiet"]) == EXIT_INVALID_CONTAINER
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"obst: {error_kind}:")


def test_inspect_maps_file_errors_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.obst"

    assert main(["inspect", str(missing)]) == EXIT_IO
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("obst: io_error:")
    assert "Traceback" not in captured.err


def test_inspect_distinguishes_corruption_from_unsupported_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corrupt = bytearray(_container())
    corrupt[-1] ^= 0xFF
    corrupt_path = _write_container(tmp_path, bytes(corrupt))

    assert main(["inspect", str(corrupt_path), "--quiet"]) == EXIT_INVALID_CONTAINER
    assert capsys.readouterr().err.startswith("obst: corrupt_container:")

    unsupported = bytearray(_container())
    unsupported[4] = 1
    crc_offset = ContainerHeader.size - 4
    struct.pack_into(
        "<I", unsupported, crc_offset, zlib.crc32(unsupported[:crc_offset])
    )
    unsupported_path = _write_container(tmp_path, bytes(unsupported))

    assert main(["inspect", str(unsupported_path), "--quiet"]) == EXIT_UNSUPPORTED
    assert capsys.readouterr().err.startswith("obst: unsupported_version:")


def test_cli_maps_resource_refusal_to_dedicated_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ResourceLimitError(
            resource=CoreResource.CHUNKS,
            scope="container",
            maximum=1,
            observed=2,
            phase="test",
        )

    source = tmp_path / "input.bin"
    source.write_bytes(b"payload")
    monkeypatch.setattr("obst_defaults.commands.publish_package", refuse)

    assert (
        main(["pack", str(source), "-o", str(tmp_path / "output.obst")])
        == EXIT_RESOURCE_LIMIT
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("obst: resource_limit:")


class _ExplodingDecodeExtension:
    extension_id = "org.example/exploding@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        specification_url="https://example.org/obst/exploding-v1"
    )

    def bind_encoder(self, parameters: bytes, /) -> Self:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> Self:
        require_no_parameters(self.extension_id, parameters)
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        assert max_output_size is None or len(data) <= max_output_size
        return data

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        raise AssertionError("inspect must never decode payloads")


def cli_extension_factory() -> tuple[Extension, ...]:
    return (_ExplodingDecodeExtension(),)


class _ConformingCliExtension(_ExplodingDecodeExtension):
    extension_id = "org.example/conforming@1"

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        assert max_output_size is None or len(data) <= max_output_size
        return data


def cli_conforming_extension_factory() -> tuple[Extension, ...]:
    return (_ConformingCliExtension(),)


def cli_conformance_factory() -> ConformanceSuite:
    return ConformanceSuite(
        (
            StageKnownAnswerCase(
                "conforming-known-answer",
                _ConformingCliExtension.extension_id,
                b"",
                b"payload",
                b"payload",
                canonical_encoding=True,
            ),
        ),
    )


class _CliExampleCommand:
    name = "example-command"
    summary = "run the command-only plugin example"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--value", required=True)

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        context.stdout.write(f"{args.value}\n")
        return EXIT_SUCCESS


def cli_command_factory() -> tuple[_CliExampleCommand, ...]:
    return (_CliExampleCommand(),)


_counting_command_factory_calls = 0


class _CountingCliCommand:
    name = "snapshot-command"
    summary = "verify one immutable command snapshot"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--value", required=True)

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        context.stdout.write(f"{args.value}\n")
        return EXIT_SUCCESS


def counting_cli_command_factory() -> tuple[_CountingCliCommand, ...]:
    global _counting_command_factory_calls
    _counting_command_factory_calls += 1
    return (_CountingCliCommand(),)


def exploding_cli_command_factory() -> tuple[_CliExampleCommand, ...]:
    raise RuntimeError("command factory must remain callback-free")
