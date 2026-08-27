"""Build the language-neutral OBST conformance vector corpus."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zlib
from pathlib import Path
from typing import cast

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerWriter,
    ExtensionRegistry,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
    encode_chunk_once,
    format_version,
)
from obst.core.wire import ChunkHeader, ContainerHeader, TerminalCommit
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import ZlibExtension, ZlibParameters
from obst_defaults.transforms.delta8 import Delta8Extension

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_ROOT = ROOT / "conformance"
INDEX_PATH = CONFORMANCE_ROOT / "index.json"

type ChunkInput = tuple[int, int, int, bytes]


def _registry() -> ExtensionRegistry:
    return ExtensionRegistry((RawExtension(), Delta8Extension(), ZlibExtension()))


def _write_container(
    manifest: Manifest,
    chunks: tuple[ChunkInput, ...],
) -> bytes:
    target = io.BytesIO()
    registry = _registry()
    writer = ContainerWriter(target, manifest)
    for stream_id, sequence, recipe_id, logical in chunks:
        writer.write_chunk(
            encode_chunk_once(
                logical,
                stream_id=stream_id,
                sequence=sequence,
                recipe=manifest.recipe(recipe_id),
                registry=registry,
            )
        )
    writer.finish()
    return target.getvalue()


def _raw_container(payload: bytes = b"hello") -> bytes:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    chunks = () if not payload else ((0, 0, 0, payload),)
    return _write_container(manifest, chunks)


def _delta8_zlib_container() -> bytes:
    zlib_extension = ZlibExtension()
    manifest = Manifest(
        recipes=(
            Recipe(
                0,
                (
                    StageSpec(Delta8Extension.extension_id),
                    StageSpec(
                        zlib_extension.extension_id,
                        zlib_extension.encode_parameters(ZlibParameters(6)),
                    ),
                ),
            ),
        ),
        streams=(
            Stream(
                0,
                BYTES_STREAM_TYPE,
                0,
                metadata=b"delta8-zlib-vector",
            ),
        ),
    )
    logical = bytes(range(96)) + b"OBST" * 8
    chunks = tuple(
        (0, sequence, 0, logical[offset : offset + 32])
        for sequence, offset in enumerate(range(0, len(logical), 32))
    )
    return _write_container(manifest, chunks)


def _multi_stream_container() -> bytes:
    manifest = Manifest(
        recipes=(
            Recipe(0, (StageSpec(RawExtension.extension_id),)),
            Recipe(1, (StageSpec(Delta8Extension.extension_id),)),
        ),
        streams=(
            Stream(0, BYTES_STREAM_TYPE, 0, metadata=b"left"),
            Stream(1, BYTES_STREAM_TYPE, 1, metadata=b"right"),
        ),
    )
    return _write_container(
        manifest,
        (
            (0, 0, 0, b"AB"),
            (1, 0, 1, b"123"),
            (0, 1, 1, b"CD"),
            (1, 1, 0, b"456"),
        ),
    )


def _unused_unknown_stage_container() -> bytes:
    manifest = Manifest(
        recipes=(
            Recipe(0, (StageSpec(RawExtension.extension_id),)),
            Recipe(1, (StageSpec("org.example/missing@1"),)),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    return _write_container(manifest, ((0, 0, 0, b"known"),))


def _container_manifest_size(encoded: bytes) -> int:
    return cast(int, struct.unpack_from("<I", encoded, 12)[0])


def _first_chunk_offset(encoded: bytes) -> int:
    return ContainerHeader.size + _container_manifest_size(encoded)


def _repair_record_crc(encoded: bytearray, offset: int, size: int) -> None:
    crc_offset = offset + size - 4
    struct.pack_into("<I", encoded, crc_offset, zlib.crc32(encoded[offset:crc_offset]))


def _repair_terminal_commit(encoded: bytearray) -> None:
    offset = len(encoded) - TerminalCommit.size
    encoded[offset + 40 : offset + 56] = hashlib.blake2s(
        encoded[:offset],
        digest_size=16,
    ).digest()
    _repair_record_crc(encoded, offset, TerminalCommit.size)


def _invalid_vectors(raw: bytes) -> dict[str, bytes]:
    invalid_magic = bytearray(raw)
    invalid_magic[:4] = b"NOPE"

    payload_crc = bytearray(raw)
    payload_offset = _first_chunk_offset(raw) + ChunkHeader.size
    payload_crc[payload_offset] ^= 0xFF

    terminal_count = bytearray(raw)
    terminal_offset = len(terminal_count) - TerminalCommit.size
    struct.pack_into("<Q", terminal_count, terminal_offset + 8, 2)
    _repair_record_crc(terminal_count, terminal_offset, TerminalCommit.size)

    bad_sequence = bytearray(raw)
    chunk_offset = _first_chunk_offset(raw)
    struct.pack_into("<Q", bad_sequence, chunk_offset + 12, 1)
    _repair_record_crc(bad_sequence, chunk_offset, ChunkHeader.size)
    _repair_terminal_commit(bad_sequence)

    unsupported_version = bytearray(raw)
    unsupported_version[5] = 2
    _repair_record_crc(unsupported_version, 0, ContainerHeader.size)

    return {
        "containers/0.1-apple/invalid/container-magic.hex": bytes(invalid_magic),
        "containers/0.1-apple/invalid/missing-terminal-commit.hex": raw[
            : -TerminalCommit.size
        ],
        "containers/0.1-apple/invalid/trailing-data.hex": raw + b"trailing",
        "containers/0.1-apple/invalid/payload-crc.hex": bytes(payload_crc),
        "containers/0.1-apple/invalid/terminal-chunk-count.hex": bytes(terminal_count),
        "containers/0.1-apple/invalid/first-sequence.hex": bytes(bad_sequence),
        "containers/0.1-apple/invalid/unsupported-version.hex": bytes(
            unsupported_version
        ),
    }


def build_vectors() -> dict[str, bytes]:
    """Return every checked-in vector by its POSIX relative path."""
    raw = _raw_container()
    empty = _raw_container(b"")
    vectors = {
        "containers/0.1-apple/golden/minimal-raw.hex": raw,
        "containers/0.1-apple/valid/delta8-zlib-multichunk.hex": (
            _delta8_zlib_container()
        ),
        "containers/0.1-apple/valid/empty-stream.hex": empty,
        "containers/0.1-apple/valid/multi-stream-interleaved.hex": (
            _multi_stream_container()
        ),
        "containers/0.1-apple/valid/unused-unknown-stage.hex": (
            _unused_unknown_stage_container()
        ),
    }
    vectors.update(_invalid_vectors(raw))
    return vectors


def _valid_expectation(*streams: tuple[int, bytes]) -> dict[str, object]:
    return {
        "result": "accept",
        "streams": [
            {
                "id": stream_id,
                "logical_size": len(logical),
                "logical_sha256": hashlib.sha256(logical).hexdigest(),
                "logical_hex": logical.hex(),
            }
            for stream_id, logical in streams
        ],
    }


def build_index(vectors: dict[str, bytes]) -> dict[str, object]:
    """Return the language-neutral catalog for the generated vector bytes."""
    logical_delta = bytes(range(96)) + b"OBST" * 8
    definitions: tuple[
        tuple[
            str,
            str,
            str,
            tuple[str, ...],
            tuple[str, ...],
            dict[str, object],
        ],
        ...,
    ] = (
        (
            "minimal-raw",
            "golden",
            "containers/0.1-apple/golden/minimal-raw.hex",
            ("raw", "terminal-commit"),
            ("obst.raw@1",),
            _valid_expectation((0, b"hello")),
        ),
        (
            "delta8-zlib-multichunk",
            "valid",
            "containers/0.1-apple/valid/delta8-zlib-multichunk.hex",
            ("delta8", "zlib", "multi-stage", "multiple-chunks"),
            ("obst.delta8@1", "obst.zlib@1"),
            _valid_expectation((0, logical_delta)),
        ),
        (
            "empty-stream",
            "valid",
            "containers/0.1-apple/valid/empty-stream.hex",
            ("empty-stream", "zero-chunks"),
            (),
            _valid_expectation((0, b"")),
        ),
        (
            "multi-stream-interleaved",
            "valid",
            "containers/0.1-apple/valid/multi-stream-interleaved.hex",
            ("multiple-streams", "interleaved", "recipe-switch"),
            ("obst.delta8@1", "obst.raw@1"),
            _valid_expectation((0, b"ABCD"), (1, b"123456")),
        ),
        (
            "unused-unknown-stage",
            "valid",
            "containers/0.1-apple/valid/unused-unknown-stage.hex",
            ("unknown-stage", "unused-recipe"),
            ("obst.raw@1",),
            _valid_expectation((0, b"known")),
        ),
        (
            "container-magic",
            "invalid",
            "containers/0.1-apple/invalid/container-magic.hex",
            ("container-header", "magic"),
            (),
            {
                "result": "reject",
                "classification": "invalid_structure",
                "rule": "docs/format.md#container-header",
            },
        ),
        (
            "missing-terminal-commit",
            "invalid",
            "containers/0.1-apple/invalid/missing-terminal-commit.hex",
            ("terminal-commit", "truncation"),
            (),
            {
                "result": "reject",
                "classification": "truncated",
                "rule": "docs/format.md#terminal-commit",
            },
        ),
        (
            "trailing-data",
            "invalid",
            "containers/0.1-apple/invalid/trailing-data.hex",
            ("terminal-commit", "trailing-data"),
            (),
            {
                "result": "reject",
                "classification": "invalid_structure",
                "rule": "docs/format.md#terminal-commit",
            },
        ),
        (
            "payload-crc",
            "invalid",
            "containers/0.1-apple/invalid/payload-crc.hex",
            ("chunk", "payload-crc"),
            (),
            {
                "result": "reject",
                "classification": "corrupt",
                "rule": "docs/format.md#chunk-records",
            },
        ),
        (
            "terminal-chunk-count",
            "invalid",
            "containers/0.1-apple/invalid/terminal-chunk-count.hex",
            ("terminal-commit", "chunk-count"),
            (),
            {
                "result": "reject",
                "classification": "invalid_structure",
                "rule": "docs/format.md#terminal-commit",
            },
        ),
        (
            "first-sequence",
            "invalid",
            "containers/0.1-apple/invalid/first-sequence.hex",
            ("chunk", "sequence"),
            (),
            {
                "result": "reject",
                "classification": "invalid_structure",
                "rule": "docs/format.md#chunk-sequence-and-interleaving",
            },
        ),
        (
            "unsupported-version",
            "invalid",
            "containers/0.1-apple/invalid/unsupported-version.hex",
            ("container-header", "version"),
            (),
            {
                "result": "reject",
                "classification": "unsupported_version",
                "rule": "docs/format.md#version-identity",
            },
        ),
    )
    return {
        "schema_version": 1,
        "format": format_version.label,
        "encoding": "ASCII hexadecimal; whitespace is insignificant",
        "vectors": [
            {
                "id": vector_id,
                "category": category,
                "path": path,
                "sha256": hashlib.sha256(vectors[path]).hexdigest(),
                "features": list(features),
                "required_extensions": list(required_extensions),
                "expected": expected,
            }
            for (
                vector_id,
                category,
                path,
                features,
                required_extensions,
                expected,
            ) in definitions
        ],
    }


def _hex_document(data: bytes) -> str:
    encoded = data.hex()
    return (
        "\n".join(
            encoded[offset : offset + 64] for offset in range(0, len(encoded), 64)
        )
        + "\n"
    )


def main() -> None:
    vectors = build_vectors()
    for relative_path, data in vectors.items():
        target = CONFORMANCE_ROOT / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_hex_document(data), encoding="ascii")
    INDEX_PATH.write_text(
        json.dumps(build_index(vectors), indent="\t", sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
