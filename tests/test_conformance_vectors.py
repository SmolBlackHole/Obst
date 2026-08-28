from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import zlib
from pathlib import Path
from typing import cast

import pytest
from scripts.build_conformance import build_index, build_vectors

from obst.core import (
    ContainerReader,
    CorruptContainerError,
    ExtensionRegistry,
    InvalidContainerError,
    MissingStageError,
    PipelineError,
    TruncatedContainerError,
    UnsupportedVersionError,
    inspect_container,
    materialize_stream,
)
from obst.core.wire import ChunkHeader, ContainerHeader, TerminalCommit
from obst_defaults.bundle import obst_extensions

ROOT = Path(__file__).parents[1]
CONFORMANCE_ROOT = ROOT / "conformance"
INDEX_PATH = CONFORMANCE_ROOT / "index.json"

type JsonObject = dict[str, object]

_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")

_FIXED_FIELD_COVERAGE = {
    "container-header": {
        "magic",
        "version",
        "header-size",
        "flags",
        "manifest-size",
        "stream-count",
        "recipe-count",
        "reserved",
        "header-crc",
    },
    "manifest-header": {
        "magic",
        "version",
        "header-size",
        "extension-count",
        "body-size",
        "body-crc",
        "header-crc",
    },
    "chunk": {
        "magic",
        "header-size",
        "flags",
        "stream-id",
        "sequence",
        "recipe-id",
        "logical-size",
        "encoded-size",
        "payload-crc",
        "logical-hash",
        "header-crc",
    },
    "terminal-commit": {
        "magic",
        "record-size",
        "flags",
        "chunk-count",
        "committed-size",
        "logical-size",
        "encoded-payload-size",
        "content-hash",
        "reserved",
        "record-crc",
    },
}

_MANIFEST_SEMANTIC_COVERAGE = {
    "identifier",
    "specification-url",
    "duplicate",
    "canonical-order",
    "unreferenced",
    "zero-recipes",
    "zero-streams",
    "zero-stages",
    "unknown-extension-index",
    "unknown-default-recipe",
    "stage-parameters",
    "metadata",
    "trailing-bytes",
}


def _index() -> JsonObject:
    return cast(
        JsonObject,
        json.loads(INDEX_PATH.read_text(encoding="utf-8")),
    )


def _records() -> tuple[JsonObject, ...]:
    return tuple(cast(list[JsonObject], _index()["vectors"]))


def _vector_bytes(record: JsonObject) -> bytes:
    path = CONFORMANCE_ROOT / cast(str, record["path"])
    return bytes.fromhex(path.read_text(encoding="ascii"))


def _record(vector_id: str) -> JsonObject:
    return next(record for record in _records() if record["id"] == vector_id)


def _expected_phase(record: JsonObject, phase: str) -> JsonObject:
    expected = cast(JsonObject, record["expected"])
    return cast(JsonObject, expected[phase])


def _heading_anchors(document: Path) -> set[str]:
    anchors: set[str] = set()
    for line in document.read_text(encoding="utf-8").splitlines():
        match = _MARKDOWN_HEADING.fullmatch(line)
        if match is None:
            continue
        heading = match.group(1).lower()
        heading = re.sub(r"[^\w\s-]", "", heading)
        anchors.add(re.sub(r"\s+", "-", heading.strip()))
    return anchors


def _record_crc_is_valid(encoded: bytes, offset: int, size: int) -> bool:
    crc_offset = offset + size - 4
    declared = cast(int, struct.unpack_from("<I", encoded, crc_offset)[0])
    return zlib.crc32(encoded[offset:crc_offset]) == declared


def _assert_terminal_integrity(encoded: bytes) -> None:
    terminal_offset = len(encoded) - TerminalCommit.size
    terminal = TerminalCommit.decode(encoded[terminal_offset:])

    assert terminal.committed_size == terminal_offset
    assert (
        terminal.content_hash
        == hashlib.blake2s(encoded[:terminal_offset], digest_size=16).digest()
    )


_STRUCTURAL_REJECTION_CLASSIFICATIONS: dict[type[InvalidContainerError], str] = {
    InvalidContainerError: "invalid_structure",
    CorruptContainerError: "corrupt",
    TruncatedContainerError: "truncated",
    UnsupportedVersionError: "unsupported_version",
}


def _classify_structural_rejection(error: InvalidContainerError) -> str:
    try:
        return _STRUCTURAL_REJECTION_CLASSIFICATIONS[type(error)]
    except KeyError as exc:
        raise AssertionError(
            f"unclassified container rejection type: {type(error).__name__}"
        ) from exc


def _classify_recovery_rejection(error: Exception) -> str:
    if type(error) is CorruptContainerError:
        return "corrupt"
    if type(error) is PipelineError:
        return "decode_failure"
    raise AssertionError(f"unclassified recovery rejection: {type(error).__name__}")


def test_conformance_index_and_vectors_are_reproducible() -> None:
    generated = build_vectors()

    assert _index() == build_index(generated)
    assert {
        path.relative_to(CONFORMANCE_ROOT).as_posix()
        for path in CONFORMANCE_ROOT.rglob("*.hex")
    } == set(generated)
    for relative_path, expected in generated.items():
        assert (
            bytes.fromhex(
                (CONFORMANCE_ROOT / relative_path).read_text(encoding="ascii")
            )
            == expected
        )


def test_conformance_catalog_schema_and_identities_are_canonical() -> None:
    index = _index()
    records = _records()
    ids = [cast(str, record["id"]) for record in records]
    paths = [cast(str, record["path"]) for record in records]

    assert index["schema_version"] == 2
    assert ids == list(dict.fromkeys(ids))
    assert paths == list(dict.fromkeys(paths))
    for record in records:
        category = cast(str, record["category"])
        assert cast(str, record["path"]).startswith(f"containers/0.1-apple/{category}/")


@pytest.mark.parametrize("record", _records(), ids=lambda record: record["id"])
def test_conformance_vector_digest(record: JsonObject) -> None:
    encoded = _vector_bytes(record)

    assert hashlib.sha256(encoded).hexdigest() == record["sha256"]


@pytest.mark.parametrize("record", _records(), ids=lambda record: record["id"])
def test_conformance_vector_requirements_are_explicit(record: JsonObject) -> None:
    required_values = cast(list[object], record["required_extensions"])

    assert all(
        type(extension_id) is str and extension_id for extension_id in required_values
    )
    required = cast(list[str], required_values)
    assert required == sorted(set(required))
    structural = _expected_phase(record, "structural")
    if structural["result"] == "reject":
        assert required == []
    expected = cast(JsonObject, record["expected"])
    recovery = cast(JsonObject | None, expected.get("recovery"))
    if recovery is not None and recovery["result"] == "unavailable":
        assert recovery["missing_extensions"] == required


def test_conformance_matrix_covers_every_fixed_record_field() -> None:
    records = _records()
    for structure, required_features in _FIXED_FIELD_COVERAGE.items():
        observed = {
            feature
            for record in records
            if structure in cast(list[str], record["features"])
            for feature in cast(list[str], record["features"])
        }
        assert required_features <= observed


def test_conformance_matrix_covers_manifest_semantics() -> None:
    observed = {
        feature
        for record in _records()
        if {"manifest", "extension", "recipe", "stream"}
        & set(cast(list[str], record["features"]))
        for feature in cast(list[str], record["features"])
    }

    assert _MANIFEST_SEMANTIC_COVERAGE <= observed


@pytest.mark.parametrize("record", _records(), ids=lambda record: record["id"])
def test_conformance_rule_links_exist(record: JsonObject) -> None:
    expected = cast(JsonObject, record["expected"])
    for phase in ("structural", "recovery"):
        outcome = cast(JsonObject | None, expected.get(phase))
        if outcome is None or "rule" not in outcome:
            continue
        relative_path, separator, fragment = cast(str, outcome["rule"]).partition("#")
        target = ROOT / relative_path

        assert separator == "#"
        assert target.is_file()
        assert fragment in _heading_anchors(target)


@pytest.mark.parametrize(
    "record",
    tuple(
        record
        for record in _records()
        if _expected_phase(record, "structural")["result"] == "accept"
    ),
    ids=lambda record: record["id"],
)
def test_structurally_valid_vectors_are_accepted(record: JsonObject) -> None:
    inspection = inspect_container(
        ContainerReader(io.BytesIO(_vector_bytes(record))),
        registry=ExtensionRegistry(()),
    )

    assert list(inspection.missing_required_stages) == record["required_extensions"]


@pytest.mark.parametrize(
    "record",
    tuple(
        record
        for record in _records()
        if _expected_phase(record, "structural")["result"] == "reject"
    ),
    ids=lambda record: record["id"],
)
def test_structurally_invalid_vectors_are_rejected(record: JsonObject) -> None:
    expected = _expected_phase(record, "structural")

    with pytest.raises(InvalidContainerError) as error:
        inspect_container(ContainerReader(io.BytesIO(_vector_bytes(record))))

    assert _classify_structural_rejection(error.value) == expected["classification"]


@pytest.mark.parametrize(
    "record",
    tuple(
        record
        for record in _records()
        if cast(JsonObject, record["expected"]).get("recovery") is not None
    ),
    ids=lambda record: record["id"],
)
def test_recovery_outcome_matches_catalog(record: JsonObject) -> None:
    recovery = _expected_phase(record, "recovery")
    encoded = _vector_bytes(record)
    result = cast(str, recovery["result"])

    if result == "success":
        registry = ExtensionRegistry(obst_extensions())
        streams = cast(list[JsonObject], recovery["streams"])
        for stream in streams:
            stream_id = cast(int, stream["id"])
            logical = materialize_stream(
                ContainerReader(io.BytesIO(encoded)),
                stream_id,
                registry,
            )
            assert len(logical) == stream["logical_size"]
            assert logical.hex() == stream["logical_hex"]
            assert hashlib.sha256(logical).hexdigest() == stream["logical_sha256"]
        return

    stream_id = cast(int, recovery["stream_id"])
    if result == "unavailable":
        with pytest.raises(MissingStageError) as missing_error:
            materialize_stream(
                ContainerReader(io.BytesIO(encoded)),
                stream_id,
                ExtensionRegistry(()),
            )
        assert missing_error.value.stage_id in cast(
            list[str], recovery["missing_extensions"]
        )
        return

    assert result == "reject"
    with pytest.raises((CorruptContainerError, PipelineError)) as recovery_error:
        materialize_stream(
            ContainerReader(io.BytesIO(encoded)),
            stream_id,
            ExtensionRegistry(obst_extensions()),
        )
    assert (
        _classify_recovery_rejection(recovery_error.value) == recovery["classification"]
    )


@pytest.mark.parametrize(
    ("error", "classification"),
    (
        (InvalidContainerError("invalid"), "invalid_structure"),
        (CorruptContainerError("corrupt"), "corrupt"),
        (TruncatedContainerError("chunk", 1, 0), "truncated"),
        (UnsupportedVersionError("OBST", (1, 0)), "unsupported_version"),
    ),
)
def test_structural_classification_uses_exact_exception_types(
    error: InvalidContainerError,
    classification: str,
) -> None:
    assert _classify_structural_rejection(error) == classification


@pytest.mark.parametrize(
    "vector_id",
    (
        "container-magic",
        "container-version",
        "manifest-magic",
        "payload-crc",
        "logical-hash",
        "logical-size",
    ),
)
def test_mutated_vectors_preserve_non_target_outer_integrity(
    vector_id: str,
) -> None:
    encoded = _vector_bytes(_record(vector_id))

    assert _record_crc_is_valid(encoded, 0, ContainerHeader.size)
    _assert_terminal_integrity(encoded)


def test_payload_crc_vector_changes_only_the_declared_payload_crc() -> None:
    encoded = _vector_bytes(_record("payload-crc"))
    manifest_size = cast(int, struct.unpack_from("<I", encoded, 12)[0])
    chunk_offset = ContainerHeader.size + manifest_size
    chunk = ChunkHeader.decode(encoded[chunk_offset : chunk_offset + ChunkHeader.size])
    payload_offset = chunk_offset + ChunkHeader.size
    payload = encoded[payload_offset : payload_offset + chunk.encoded_size]

    assert zlib.crc32(payload) != chunk.payload_crc32
    assert hashlib.blake2s(payload, digest_size=16).digest() == chunk.logical_hash
