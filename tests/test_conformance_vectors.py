from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import cast

import pytest
from scripts.build_conformance import build_index, build_vectors

from obst.core import (
    ContainerReader,
    CorruptContainerError,
    ExtensionRegistry,
    InvalidContainerError,
    TruncatedContainerError,
    UnsupportedVersionError,
    inspect_container,
    materialize_stream,
)
from obst_defaults.bundle import obst_extensions

ROOT = Path(__file__).parents[1]
CONFORMANCE_ROOT = ROOT / "conformance"
INDEX_PATH = CONFORMANCE_ROOT / "index.json"

type JsonObject = dict[str, object]


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
    if record["category"] == "invalid":
        assert required == []


@pytest.mark.parametrize(
    "record",
    tuple(record for record in _records() if record["category"] != "invalid"),
    ids=lambda record: record["id"],
)
def test_valid_conformance_vectors_recover_declared_streams(
    record: JsonObject,
) -> None:
    encoded = _vector_bytes(record)
    structural = inspect_container(
        ContainerReader(io.BytesIO(encoded)),
        registry=ExtensionRegistry(()),
    )
    registry = ExtensionRegistry(obst_extensions())
    expected = cast(JsonObject, record["expected"])
    expected_streams = cast(list[JsonObject], expected["streams"])

    assert list(structural.missing_required_stages) == record["required_extensions"]
    inspection = inspect_container(
        ContainerReader(io.BytesIO(encoded)), registry=registry
    )
    assert inspection.stream_count == len(expected_streams)
    for stream in expected_streams:
        stream_id = cast(int, stream["id"])
        logical = materialize_stream(
            ContainerReader(io.BytesIO(encoded)),
            stream_id,
            registry,
        )
        assert len(logical) == stream["logical_size"]
        assert logical.hex() == stream["logical_hex"]
        assert hashlib.sha256(logical).hexdigest() == stream["logical_sha256"]


_REJECTION_TYPES: dict[str, type[Exception]] = {
    "invalid_structure": InvalidContainerError,
    "corrupt": CorruptContainerError,
    "truncated": TruncatedContainerError,
    "unsupported_version": UnsupportedVersionError,
}


@pytest.mark.parametrize(
    "record",
    tuple(record for record in _records() if record["category"] == "invalid"),
    ids=lambda record: record["id"],
)
def test_invalid_conformance_vectors_are_rejected(record: JsonObject) -> None:
    expected = cast(JsonObject, record["expected"])
    classification = cast(str, expected["classification"])

    with pytest.raises(_REJECTION_TYPES[classification]):
        inspect_container(ContainerReader(io.BytesIO(_vector_bytes(record))))
