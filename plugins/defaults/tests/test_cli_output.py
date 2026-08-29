from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from obst.cli import HumanOutputStyle, escape_human_text
from obst.cli.output import (
    INSPECTION_JSON_SCHEMA_VERSION,
    render_inspection_human,
    render_inspection_json,
)
from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerInspection,
    ContainerReader,
    ContainerWriter,
    ExtensionRegistry,
    InspectionInterpretation,
    InspectionInterpretationPolicy,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
    encode_chunk_once,
    format_version,
    inspect_container,
)

from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import ZlibExtension
from obst_defaults.files import (
    FileExtension,
    FileExtractionCleanupIssue,
    FileExtractionResult,
)
from obst_defaults.output import write_unpack_result


def _inspect(
    manifest: Manifest,
    chunks: tuple[tuple[int, bytes, int | None], ...],
    *,
    with_interpreters: bool = False,
) -> ContainerInspection:
    target = io.BytesIO()
    stage_registry = ExtensionRegistry((RawExtension(), ZlibExtension()))
    writer = ContainerWriter(target, manifest)
    sequences = {stream.stream_id: 0 for stream in manifest.streams}
    for stream_id, payload, recipe_id in chunks:
        selected_recipe_id = (
            manifest.stream(stream_id).default_recipe_id
            if recipe_id is None
            else recipe_id
        )
        writer.write_chunk(
            encode_chunk_once(
                payload,
                stream_id=stream_id,
                sequence=sequences[stream_id],
                recipe=manifest.recipe(selected_recipe_id),
                registry=stage_registry,
            )
        )
        sequences[stream_id] += 1
    writer.finish()
    reader = ContainerReader(io.BytesIO(target.getvalue()))
    inspection_extensions = (
        (RawExtension(), ZlibExtension(), FileExtension())
        if with_interpreters
        else (RawExtension(),)
    )
    return inspect_container(
        reader,
        registry=ExtensionRegistry(inspection_extensions),
        interpretation_policy=(
            InspectionInterpretationPolicy(
                frozenset(extension.extension_id for extension in inspection_extensions)
            )
            if with_interpreters
            else None
        ),
    )


def _raw_inspection() -> ContainerInspection:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    return _inspect(manifest, ((0, b"x" * 64, None),))


def test_unpack_output_reports_cleanup_without_claiming_publication_failed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_directory = tmp_path / "restored"
    restored = output_directory / "apple.txt"
    issue = FileExtractionCleanupIssue(
        str(output_directory / ".obst-unpack-residual"),
        "cleanup failed",
    )
    result = FileExtractionResult(output_directory, (restored,), (issue,))

    write_unpack_result(result, stdout=sys.stdout, stderr=sys.stderr)

    captured = capsys.readouterr()
    assert captured.out.startswith("Unpacked 1 file")
    assert "cleanup_required: published output is complete" in captured.err
    assert issue.resource in captured.err


def test_unpack_output_warns_when_windows_origin_is_not_propagated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_directory = tmp_path / "restored"
    result = FileExtractionResult(output_directory, (), ())

    write_unpack_result(
        result,
        stdout=sys.stdout,
        stderr=sys.stderr,
        windows_origin_not_propagated=True,
    )

    captured = capsys.readouterr()
    assert "Unpacked 0 files" in captured.out
    assert "input has Windows Mark of the Web" in captured.err
    assert "extracted files do not inherit it" in captured.err


def test_unpack_json_keeps_structured_cleanup_and_stderr_warnings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_directory = tmp_path / "restored"
    restored = output_directory / "apple.txt"
    issue = FileExtractionCleanupIssue(
        str(output_directory / ".obst-unpack-residual"),
        "cleanup failed",
    )
    result = FileExtractionResult(output_directory, (restored,), (issue,))

    write_unpack_result(
        result,
        stdout=sys.stdout,
        stderr=sys.stderr,
        windows_origin_not_propagated=True,
        json_output=True,
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert document["cleanup_issues"] == [
        {"resource": issue.resource, "reason": issue.reason}
    ]
    assert document["windows_origin_not_propagated"] is True
    assert "cleanup_required" in captured.err
    assert "input has Windows Mark of the Web" in captured.err


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("apple\u202ebat.exe", "apple\\u202ebat.exe"),
        ("line\nfeed", "line\\u000afeed"),
        ("paragraph\u2029break", "paragraph\\u2029break"),
        ("family\u200dname", "family\u200dname"),
    ),
)
def test_human_text_escapes_terminal_controls_without_flattening_unicode(
    value: str,
    expected: str,
) -> None:
    assert escape_human_text(value) == expected


@pytest.mark.parametrize(
    ("stored_size", "original_size", "expected"),
    (
        (721, 1000, "27.9% smaller (72.1% of original)"),
        (1279, 1000, "27.9% larger (127.9% of original)"),
        (1000, 1000, "same size (100.0% of original)"),
        (0, 0, "n/a (empty input)"),
    ),
)
def test_compression_summary_leads_with_the_size_change(
    stored_size: int,
    original_size: int,
    expected: str,
) -> None:
    inspection = _raw_inspection()
    inspection = replace(
        inspection,
        summary=replace(
            inspection.summary,
            encoded_size=stored_size,
            logical_size=original_size,
        ),
        resources=replace(
            inspection.resources,
            max_materialized_stream_size=original_size,
        ),
        streams=(replace(inspection.streams[0], logical_size=original_size),),
    )

    output = render_inspection_human(inspection)

    assert f"{'Compression':<29} {expected}" in output


def test_human_renderer_preserves_readable_inspection_sections() -> None:
    inspection = _raw_inspection()

    output = render_inspection_human(inspection)

    assert f"OBST container {format_version.label}" in output
    assert f"{'Streams':<29} 1" in output
    assert f"{'Recipes':<29} 1" in output
    assert f"{'Chunks':<29} 1" in output
    assert f"{'Container size':<29} {inspection.encoded_size} B" in output
    assert f"{'Original size':<29} 64 B (committed)" in output
    assert f"{'Integrity':<29} valid (terminal commit and encoded CRCs)" in output
    assert f"{'Required decoders available':<29} yes" in output
    assert f"{'Logical recovery':<29} not attempted" in output
    assert "\nStreams\n  [0] obst.bytes@1" in output
    assert "Recipe usage: yes (1 total; recipe 0: 1)" in output
    assert "\nRecipes\n  [0] obst.raw@1 | 1 chunk" in output
    assert "\nResource footprint\n" in output
    assert "Manifest " in output
    assert "largest chunk 64 B logical / 64 B encoded" in output
    assert "Stage executions 1 | largest stream 64 B if materialized" in output
    assert "\nStage capabilities\n  obst.raw@1 (RAW): decoder available" in output
    assert "Declared by recipe: 0" in output
    assert "Used by chunks: yes (1 total; recipe 0: 1)" in output


class _InteractiveText(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_human_output_style_respects_terminal_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)

    interactive = HumanOutputStyle.for_stream(_InteractiveText())
    redirected = HumanOutputStyle.for_stream(io.StringIO())

    assert interactive.color is True
    assert interactive.heading("Streams") == "\x1b[1;36mStreams\x1b[0m"
    assert redirected.color is False
    assert redirected.heading("Streams") == "Streams"

    monkeypatch.setenv("NO_COLOR", "1")
    assert HumanOutputStyle.for_stream(_InteractiveText()).color is False

    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert HumanOutputStyle.for_stream(io.StringIO()).color is True


def test_colored_human_renderer_keeps_plain_renderer_and_json_inert() -> None:
    inspection = _raw_inspection()

    plain = render_inspection_human(inspection)
    colored = render_inspection_human(
        inspection,
        style=HumanOutputStyle(color=True),
    )

    assert "\x1b[" not in plain
    assert "\x1b[31m" in colored
    assert "\x1b[32m" in colored
    assert "\x1b[90m" in colored
    assert "\x1b[" not in render_inspection_json(inspection)


def test_human_renderer_uses_the_compact_apple_silhouette() -> None:
    output = render_inspection_human(_raw_inspection())

    apple, _separator, _sections = output.partition("\nStreams\n")
    assert apple.splitlines()[-1].lstrip().startswith("██████████████")
    assert "              ██████" not in apple.splitlines()


def test_human_renderer_escapes_interpreter_supplied_labels() -> None:
    inspection = _raw_inspection()
    inspection = replace(
        inspection,
        streams=(
            replace(
                inspection.streams[0],
                metadata=InspectionInterpretation(label="safe\u202eevil\nname"),
            ),
        ),
    )

    output = render_inspection_human(inspection)

    assert "safe\\u202eevil\\u000aname" in output
    assert "\u202e" not in output


@pytest.mark.parametrize(
    ("chunks", "expected"),
    (
        ((), "0 chunks"),
        (((0, b"a", None),), "1 chunk"),
        (((0, b"a", None), (0, b"b", None)), "2 chunks"),
    ),
)
def test_human_renderer_pluralizes_stream_and_recipe_chunk_counts(
    chunks: tuple[tuple[int, bytes, int | None], ...],
    expected: str,
) -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )

    output = render_inspection_human(_inspect(manifest, chunks))

    assert f"obst.bytes@1 | {expected} |" in output
    assert f"obst.raw@1 | {expected}" in output


def test_json_renderer_exposes_complete_structural_inspection() -> None:
    inspection = _raw_inspection()

    document = json.loads(render_inspection_json(inspection))

    assert document["schema_version"] == INSPECTION_JSON_SCHEMA_VERSION == 6
    assert document["format"] == {
        "codename": format_version.codename,
        "label": format_version.label,
        "major": 0,
        "minor": 1,
        "name": "OBST",
    }
    assert document["container_size"] == inspection.encoded_size
    assert document["original_size"] == 64
    assert document["required_decoders_available"] is True
    assert document["missing_required_stages"] == []
    assert document["missing_declared_stages"] == []
    assert document["logical_recovery"] == "not_attempted"
    assert document["interpretation_policy"] == {"extension_ids": []}
    assert document["resource_footprint"] == {
        "chunk_count": 1,
        "container_size": inspection.encoded_size,
        "extension_count": 2,
        "logical_size": 64,
        "manifest_size": inspection.resources.manifest_size,
        "max_encoded_chunk_size": 64,
        "max_logical_chunk_size": 64,
        "max_materialized_stream_size": 64,
        "max_stages_per_recipe": 1,
        "recipe_count": 1,
        "stage_executions": 1,
        "stream_count": 1,
        "total_stage_count": 1,
    }
    assert document["stream_details"] == [
        {
            "chunks": 1,
            "default_recipe": 0,
            "encoded_payload_size": 64,
            "id": 0,
            "metadata_hex": "",
            "metadata_interpretation": None,
            "original_size": 64,
            "recipe_usage": [{"chunks": 1, "recipe_id": 0}],
            "type": BYTES_STREAM_TYPE,
        }
    ]
    assert document["recipe_details"] == [
        {
            "chunks": 1,
            "id": 0,
            "stages": [
                {
                    "id": RawExtension.extension_id,
                    "parameters_hex": "",
                    "parameters_interpretation": None,
                }
            ],
        }
    ]


def test_explicit_interpreters_add_meaning_without_replacing_raw_bytes() -> None:
    file_extension = FileExtension()
    metadata = file_extension.encode_file_name("apple.txt")
    manifest = Manifest(
        recipes=(Recipe(7, (StageSpec(ZlibExtension.extension_id, b"\x09"),)),),
        streams=(Stream(2, file_extension.extension_id, 7, metadata),),
    )
    inspection = _inspect(
        manifest,
        ((2, b"fruit" * 100, None),),
        with_interpreters=True,
    )

    document = json.loads(render_inspection_json(inspection))

    stream = document["stream_details"][0]
    assert stream["metadata_hex"] == metadata.hex()
    assert stream["metadata_interpretation"] == {
        "error": None,
        "fields": {"name": "apple.txt"},
        "label": "apple.txt",
    }
    stage = document["recipe_details"][0]["stages"][0]
    assert stage["parameters_hex"] == "09"
    assert stage["parameters_interpretation"] == {
        "error": None,
        "fields": {"compression_level": 9},
        "label": None,
    }
    assert "[2] apple.txt" in render_inspection_human(inspection)


def test_interpretation_error_does_not_hide_raw_metadata() -> None:
    file_extension = FileExtension()
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, file_extension.extension_id, 0, b"\xff"),),
    )
    inspection = _inspect(manifest, (), with_interpreters=True)

    document = json.loads(render_inspection_json(inspection))
    stream = document["stream_details"][0]

    assert stream["metadata_hex"] == "ff"
    assert stream["metadata_interpretation"]["error"] == (
        "file metadata is not valid UTF-8"
    )
    assert "Metadata interpretation: file metadata is not valid UTF-8" in (
        render_inspection_human(inspection)
    )
