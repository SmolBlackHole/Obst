"""Build the language-neutral OBST conformance vector corpus."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerWriter,
    ExtensionDeclaration,
    ExtensionRegistry,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
    encode_chunk_once,
    format_version,
)
from obst.core.wire import (
    ChunkHeader,
    ContainerHeader,
    ManifestHeader,
    TerminalCommit,
    extension_declaration,
    recipe_declaration,
    stage_declaration,
    stream_declaration,
    uint32,
)
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import ZlibExtension, ZlibParameters
from obst_defaults.transforms.delta8 import Delta8Extension

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_ROOT = ROOT / "conformance"
INDEX_PATH = CONFORMANCE_ROOT / "index.json"

type ChunkInput = tuple[int, int, int, bytes]
type VectorCategory = Literal["golden", "valid", "invalid"]
type JsonObject = dict[str, object]

_MATRIX_STAGE_ID = "org.example/alpha@1"
_MATRIX_STREAM_TYPE = "org.example/bravo@1"
_UNKNOWN_STAGE_ID = "test.foo@1"
_SPECIFICATION_URL = "https://example.org/specs/raw-v1"


@dataclass(frozen=True, slots=True)
class VectorDefinition:
    """One generated vector and its portable expected outcome."""

    vector_id: str
    category: VectorCategory
    encoded: bytes
    features: tuple[str, ...]
    required_extensions: tuple[str, ...]
    expected: JsonObject

    @property
    def path(self) -> str:
        return f"containers/{format_version.label}/{self.category}/{self.vector_id}.hex"


@dataclass(frozen=True, slots=True)
class ManifestOffsets:
    """Offsets within one canonically encoded manifest."""

    extension_ids: dict[str, int]
    extension_urls: dict[str, int]
    extensions_end: int
    recipe_offsets: dict[int, int]
    recipe_stage_offsets: dict[int, tuple[int, ...]]
    streams_start: int
    stream_offsets: dict[int, int]


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


def _raw_manifest(
    *,
    recipe_id: int = 0,
    stream_id: int = 0,
) -> Manifest:
    return Manifest(
        recipes=(Recipe(recipe_id, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(stream_id, BYTES_STREAM_TYPE, recipe_id),),
    )


def _raw_container(payload: bytes = b"hello") -> bytes:
    manifest = _raw_manifest()
    chunks = () if not payload else ((0, 0, 0, payload),)
    return _write_container(manifest, chunks)


def _empty_raw_chunk_container() -> bytes:
    return _write_container(_raw_manifest(), ((0, 0, 0, b""),))


def _mixed_empty_chunks_container() -> bytes:
    return _write_container(
        _raw_manifest(),
        (
            (0, 0, 0, b""),
            (0, 1, 0, b"middle"),
            (0, 2, 0, b""),
        ),
    )


def _empty_zlib_chunk_container() -> bytes:
    zlib_extension = ZlibExtension()
    manifest = Manifest(
        recipes=(
            Recipe(
                0,
                (
                    StageSpec(
                        zlib_extension.extension_id,
                        zlib_extension.encode_parameters(ZlibParameters(6)),
                    ),
                ),
            ),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    return _write_container(manifest, ((0, 0, 0, b""),))


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


def _matrix_manifest() -> Manifest:
    return Manifest(
        recipes=(
            Recipe(1, (StageSpec(_MATRIX_STAGE_ID),)),
            Recipe(7, (StageSpec(_MATRIX_STAGE_ID),)),
        ),
        streams=(
            Stream(2, _MATRIX_STREAM_TYPE, 1, b"two"),
            Stream(8, _MATRIX_STREAM_TYPE, 7, b"eight"),
        ),
    )


def _sparse_ids_container() -> bytes:
    return _write_container(_matrix_manifest(), ())


def _specification_url_manifest() -> Manifest:
    return Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
        extensions=(
            ExtensionDeclaration(RawExtension.extension_id, _SPECIFICATION_URL),
        ),
    )


def _specification_url_container() -> bytes:
    return _write_container(_specification_url_manifest(), ())


def _maximum_ids_container() -> bytes:
    manifest = _raw_manifest(
        recipe_id=uint32.maximum,
        stream_id=uint32.maximum,
    )
    return _write_container(
        manifest,
        ((uint32.maximum, 0, uint32.maximum, b"maximum ids"),),
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


def _container_manifest_size(encoded: bytes | bytearray) -> int:
    return cast(int, struct.unpack_from("<I", encoded, 12)[0])


def _manifest_bytes(encoded: bytes) -> bytes:
    start = ContainerHeader.size
    return encoded[start : start + _container_manifest_size(encoded)]


def _first_chunk_offset(encoded: bytes) -> int:
    return ContainerHeader.size + _container_manifest_size(encoded)


def _chunk_offsets(encoded: bytes) -> tuple[int, ...]:
    offsets: list[int] = []
    offset = _first_chunk_offset(encoded)
    terminal_offset = len(encoded) - TerminalCommit.size
    while offset < terminal_offset:
        offsets.append(offset)
        chunk = ChunkHeader.decode(encoded[offset : offset + ChunkHeader.size])
        offset += ChunkHeader.size + chunk.encoded_size
    assert offset == terminal_offset
    return tuple(offsets)


def _manifest_offsets(manifest: Manifest) -> ManifestOffsets:
    offset = ManifestHeader.size
    extension_ids: dict[str, int] = {}
    extension_urls: dict[str, int] = {}
    for extension in manifest.extensions:
        encoded_id = extension.extension_id.encode("ascii")
        encoded_url = (
            b""
            if extension.specification_url is None
            else extension.specification_url.encode("ascii")
        )
        extension_ids[extension.extension_id] = offset + extension_declaration.size
        extension_urls[extension.extension_id] = (
            offset + extension_declaration.size + len(encoded_id)
        )
        offset += extension_declaration.size + len(encoded_id) + len(encoded_url)
    extensions_end = offset

    recipe_offsets: dict[int, int] = {}
    recipe_stage_offsets: dict[int, tuple[int, ...]] = {}
    for recipe in sorted(manifest.recipes, key=lambda item: item.recipe_id):
        recipe_offsets[recipe.recipe_id] = offset
        offset += recipe_declaration.size
        stage_offsets: list[int] = []
        for stage in recipe.stages:
            stage_offsets.append(offset)
            offset += stage_declaration.size + len(stage.parameters)
        recipe_stage_offsets[recipe.recipe_id] = tuple(stage_offsets)
    streams_start = offset

    stream_offsets: dict[int, int] = {}
    for stream in sorted(manifest.streams, key=lambda item: item.stream_id):
        stream_offsets[stream.stream_id] = offset
        offset += stream_declaration.size + len(stream.metadata)

    return ManifestOffsets(
        extension_ids=extension_ids,
        extension_urls=extension_urls,
        extensions_end=extensions_end,
        recipe_offsets=recipe_offsets,
        recipe_stage_offsets=recipe_stage_offsets,
        streams_start=streams_start,
        stream_offsets=stream_offsets,
    )


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


def _repair_manifest_integrity(encoded: bytearray) -> None:
    manifest_offset = ContainerHeader.size
    manifest_size = _container_manifest_size(encoded)
    body_offset = manifest_offset + ManifestHeader.size
    body_end = manifest_offset + manifest_size
    struct.pack_into(
        "<I",
        encoded,
        manifest_offset + 16,
        zlib.crc32(encoded[body_offset:body_end]),
    )
    _repair_record_crc(encoded, manifest_offset, ManifestHeader.size)
    _repair_terminal_commit(encoded)


def _mutate_committed_record(
    encoded: bytes,
    *,
    record_offset: int,
    record_size: int,
    field_offset: int,
    replacement: bytes,
    repair_record_crc: bool = True,
) -> bytes:
    mutated = bytearray(encoded)
    offset = record_offset + field_offset
    mutated[offset : offset + len(replacement)] = replacement
    if repair_record_crc:
        _repair_record_crc(mutated, record_offset, record_size)
    _repair_terminal_commit(mutated)
    return bytes(mutated)


def _mutate_manifest_body(
    encoded: bytes,
    *replacements: tuple[int, bytes],
) -> bytes:
    mutated = bytearray(encoded)
    for manifest_offset, replacement in replacements:
        absolute = ContainerHeader.size + manifest_offset
        mutated[absolute : absolute + len(replacement)] = replacement
    _repair_manifest_integrity(mutated)
    return bytes(mutated)


def _manifest_with_body(
    encoded_manifest: bytes,
    body: bytes,
    *,
    extension_count: int | None = None,
) -> bytes:
    header = ManifestHeader.decode(encoded_manifest[: ManifestHeader.size])
    return (
        ManifestHeader(
            extension_count=(
                header.extension_count if extension_count is None else extension_count
            ),
            body_size=len(body),
            body_crc32=zlib.crc32(body),
        ).encode()
        + body
    )


def _replace_manifest(
    encoded: bytes,
    manifest: bytes,
    *,
    recipe_count: int,
    stream_count: int,
) -> bytes:
    old_terminal_offset = len(encoded) - TerminalCommit.size
    old_terminal = TerminalCommit.decode(encoded[old_terminal_offset:])
    chunks = encoded[
        ContainerHeader.size + _container_manifest_size(encoded) : old_terminal_offset
    ]
    header = ContainerHeader(
        manifest_size=len(manifest),
        stream_count=stream_count,
        recipe_count=recipe_count,
    ).encode()
    committed = header + manifest + chunks
    terminal = TerminalCommit(
        chunk_count=old_terminal.chunk_count,
        committed_size=len(committed),
        logical_size=old_terminal.logical_size,
        encoded_payload_size=old_terminal.encoded_payload_size,
        content_hash=hashlib.blake2s(committed, digest_size=16).digest(),
    ).encode()
    return committed + terminal


def _used_unknown_stage_container(raw: bytes) -> bytes:
    offsets = _manifest_offsets(_raw_manifest())
    assert len(_UNKNOWN_STAGE_ID) == len(RawExtension.extension_id)
    return _mutate_manifest_body(
        raw,
        (
            offsets.extension_ids[RawExtension.extension_id],
            _UNKNOWN_STAGE_ID.encode("ascii"),
        ),
    )


def _success_expectation(*streams: tuple[int, bytes]) -> JsonObject:
    return {
        "structural": {"result": "accept"},
        "recovery": {
            "result": "success",
            "streams": [
                {
                    "id": stream_id,
                    "logical_size": len(logical),
                    "logical_sha256": hashlib.sha256(logical).hexdigest(),
                    "logical_hex": logical.hex(),
                }
                for stream_id, logical in streams
            ],
        },
    }


def _unavailable_expectation(
    *,
    stream_id: int,
    missing_extensions: tuple[str, ...],
) -> JsonObject:
    return {
        "structural": {"result": "accept"},
        "recovery": {
            "result": "unavailable",
            "stream_id": stream_id,
            "missing_extensions": list(missing_extensions),
            "rule": "docs/format.md#validity-and-decoder-availability",
        },
    }


def _structural_rejection(classification: str, rule: str) -> JsonObject:
    return {
        "structural": {
            "result": "reject",
            "classification": classification,
            "rule": rule,
        }
    }


def _recovery_rejection(
    *,
    stream_id: int,
    classification: str,
) -> JsonObject:
    return {
        "structural": {"result": "accept"},
        "recovery": {
            "result": "reject",
            "stream_id": stream_id,
            "classification": classification,
            "rule": "docs/format.md#validity-and-decoder-availability",
        },
    }


def _vector(
    vector_id: str,
    category: VectorCategory,
    encoded: bytes,
    features: tuple[str, ...],
    required_extensions: tuple[str, ...],
    expected: JsonObject,
) -> VectorDefinition:
    return VectorDefinition(
        vector_id=vector_id,
        category=category,
        encoded=encoded,
        features=features,
        required_extensions=tuple(sorted(required_extensions)),
        expected=expected,
    )


def _valid_definitions(raw: bytes) -> tuple[VectorDefinition, ...]:
    logical_delta = bytes(range(96)) + b"OBST" * 8
    return (
        _vector(
            "minimal-raw",
            "golden",
            raw,
            ("raw", "terminal-commit"),
            (RawExtension.extension_id,),
            _success_expectation((0, b"hello")),
        ),
        _vector(
            "delta8-zlib-multichunk",
            "valid",
            _delta8_zlib_container(),
            ("delta8", "zlib", "multi-stage", "multiple-chunks"),
            (Delta8Extension.extension_id, ZlibExtension.extension_id),
            _success_expectation((0, logical_delta)),
        ),
        _vector(
            "empty-stream",
            "valid",
            _raw_container(b""),
            ("empty-stream", "zero-chunks"),
            (),
            _success_expectation((0, b"")),
        ),
        _vector(
            "empty-raw-chunk",
            "valid",
            _empty_raw_chunk_container(),
            ("empty-chunk", "raw", "zero-length-payload"),
            (RawExtension.extension_id,),
            _success_expectation((0, b"")),
        ),
        _vector(
            "mixed-empty-chunks",
            "valid",
            _mixed_empty_chunks_container(),
            ("empty-chunk", "multiple-chunks", "sequence"),
            (RawExtension.extension_id,),
            _success_expectation((0, b"middle")),
        ),
        _vector(
            "empty-zlib-chunk",
            "valid",
            _empty_zlib_chunk_container(),
            ("empty-chunk", "zlib", "nonempty-encoded-payload"),
            (ZlibExtension.extension_id,),
            _success_expectation((0, b"")),
        ),
        _vector(
            "multi-stream-interleaved",
            "valid",
            _multi_stream_container(),
            ("multiple-streams", "interleaved", "recipe-switch"),
            (Delta8Extension.extension_id, RawExtension.extension_id),
            _success_expectation((0, b"ABCD"), (1, b"123456")),
        ),
        _vector(
            "sparse-identifiers",
            "valid",
            _sparse_ids_container(),
            ("multiple-recipes", "multiple-streams", "sparse-identifiers"),
            (),
            _success_expectation((2, b""), (8, b"")),
        ),
        _vector(
            "maximum-identifiers",
            "valid",
            _maximum_ids_container(),
            ("maximum-u32", "recipe-id", "stream-id"),
            (RawExtension.extension_id,),
            _success_expectation((uint32.maximum, b"maximum ids")),
        ),
        _vector(
            "specification-url",
            "valid",
            _specification_url_container(),
            ("extension", "specification-url", "zero-chunks"),
            (),
            _success_expectation((0, b"")),
        ),
        _vector(
            "unused-unknown-stage",
            "valid",
            _unused_unknown_stage_container(),
            ("unknown-stage", "unused-recipe"),
            (RawExtension.extension_id,),
            _success_expectation((0, b"known")),
        ),
        _vector(
            "used-unknown-stage",
            "valid",
            _used_unknown_stage_container(raw),
            ("missing-capability", "unknown-stage", "used-recipe"),
            (_UNKNOWN_STAGE_ID,),
            _unavailable_expectation(
                stream_id=0,
                missing_extensions=(_UNKNOWN_STAGE_ID,),
            ),
        ),
    )


def _invalid_definitions(raw: bytes) -> tuple[VectorDefinition, ...]:
    definitions: list[VectorDefinition] = []

    def reject(
        vector_id: str,
        encoded: bytes,
        features: tuple[str, ...],
        classification: str,
        rule: str,
    ) -> None:
        definitions.append(
            _vector(
                vector_id,
                "invalid",
                encoded,
                features,
                (),
                _structural_rejection(classification, rule),
            )
        )

    container_rule = "docs/format.md#container-header"
    manifest_rule = "docs/format.md#manifest"
    extension_rule = "docs/format.md#extension-table"
    recipe_rule = "docs/format.md#recipe-entries"
    stream_rule = "docs/format.md#stream-entries"
    chunk_rule = "docs/format.md#chunk-framing"
    terminal_rule = "docs/format.md#terminal-commit-record"

    manifest_size = _container_manifest_size(raw)
    chunk_offset = _first_chunk_offset(raw)
    chunk = ChunkHeader.decode(raw[chunk_offset : chunk_offset + ChunkHeader.size])
    payload_offset = chunk_offset + ChunkHeader.size
    payload_end = payload_offset + chunk.encoded_size

    reject(
        "truncated-container-header",
        raw[: ContainerHeader.size - 1],
        ("container-header", "truncation"),
        "truncated",
        container_rule,
    )
    reject(
        "truncated-manifest",
        raw[: ContainerHeader.size + manifest_size - 1],
        ("manifest", "truncation"),
        "truncated",
        manifest_rule,
    )
    reject(
        "truncated-chunk-header",
        raw[: chunk_offset + ChunkHeader.size - 1],
        ("chunk", "header", "truncation"),
        "truncated",
        chunk_rule,
    )
    reject(
        "truncated-chunk-payload",
        raw[: payload_end - 1],
        ("chunk", "payload", "truncation"),
        "truncated",
        chunk_rule,
    )
    reject(
        "missing-terminal-commit",
        raw[: -TerminalCommit.size],
        ("terminal-commit", "truncation", "zero-terminal-bytes"),
        "truncated",
        terminal_rule,
    )
    reject(
        "truncated-terminal-commit",
        raw[:-1],
        ("terminal-commit", "truncation", "partial-record"),
        "truncated",
        terminal_rule,
    )

    container_mutations = (
        ("container-magic", 0, b"NOPE", "invalid_structure", ("magic",), True),
        (
            "container-version",
            5,
            b"\x02",
            "unsupported_version",
            ("version",),
            True,
        ),
        (
            "container-header-size",
            6,
            struct.pack("<H", 0),
            "invalid_structure",
            ("header-size",),
            True,
        ),
        (
            "container-flags",
            8,
            struct.pack("<I", 1),
            "invalid_structure",
            ("flags",),
            True,
        ),
        (
            "container-manifest-size",
            12,
            struct.pack("<I", manifest_size - 1),
            "invalid_structure",
            ("manifest-size",),
            True,
        ),
        (
            "container-stream-count",
            16,
            struct.pack("<I", 2),
            "truncated",
            ("stream-count",),
            True,
        ),
        (
            "container-recipe-count",
            20,
            struct.pack("<I", 2),
            "invalid_structure",
            ("recipe-count",),
            True,
        ),
        (
            "container-reserved",
            24,
            struct.pack("<I", 1),
            "invalid_structure",
            ("reserved",),
            True,
        ),
        (
            "container-header-crc",
            28,
            struct.pack("<I", 0),
            "corrupt",
            ("header-crc",),
            False,
        ),
    )
    for (
        vector_id,
        field_offset,
        replacement,
        classification,
        field_features,
        repair_crc,
    ) in container_mutations:
        reject(
            vector_id,
            _mutate_committed_record(
                raw,
                record_offset=0,
                record_size=ContainerHeader.size,
                field_offset=field_offset,
                replacement=replacement,
                repair_record_crc=repair_crc,
            ),
            ("container-header", *field_features),
            classification,
            container_rule,
        )

    manifest_offset = ContainerHeader.size
    manifest_mutations = (
        ("manifest-magic", 0, b"NOPE", "invalid_structure", ("magic",), True),
        (
            "manifest-version",
            5,
            b"\x02",
            "unsupported_version",
            ("version",),
            True,
        ),
        (
            "manifest-header-size",
            6,
            struct.pack("<H", 0),
            "invalid_structure",
            ("header-size",),
            True,
        ),
        (
            "manifest-extension-count",
            8,
            struct.pack("<I", 0),
            "invalid_structure",
            ("extension-count",),
            True,
        ),
        (
            "manifest-body-size",
            12,
            struct.pack("<I", 0),
            "invalid_structure",
            ("body-size",),
            True,
        ),
        (
            "manifest-body-crc",
            16,
            struct.pack("<I", 0),
            "corrupt",
            ("body-crc",),
            True,
        ),
        (
            "manifest-header-crc",
            20,
            struct.pack("<I", 0),
            "corrupt",
            ("header-crc",),
            False,
        ),
    )
    for (
        vector_id,
        field_offset,
        replacement,
        classification,
        field_features,
        repair_crc,
    ) in manifest_mutations:
        reject(
            vector_id,
            _mutate_committed_record(
                raw,
                record_offset=manifest_offset,
                record_size=ManifestHeader.size,
                field_offset=field_offset,
                replacement=replacement,
                repair_record_crc=repair_crc,
            ),
            ("manifest-header", *field_features),
            classification,
            manifest_rule,
        )

    raw_offsets = _manifest_offsets(_raw_manifest())
    raw_id_offset = raw_offsets.extension_ids[RawExtension.extension_id]
    reject(
        "extension-id-uppercase",
        _mutate_manifest_body(raw, (raw_id_offset, b"O")),
        ("extension", "identifier", "uppercase"),
        "invalid_structure",
        extension_rule,
    )
    reject(
        "extension-id-version-zero",
        _mutate_manifest_body(
            raw,
            (
                raw_id_offset + len(RawExtension.extension_id) - 1,
                b"0",
            ),
        ),
        ("extension", "identifier", "zero-version"),
        "invalid_structure",
        extension_rule,
    )
    reject(
        "extension-id-non-ascii",
        _mutate_manifest_body(raw, (raw_id_offset, b"\xff")),
        ("extension", "identifier", "non-ascii"),
        "invalid_structure",
        extension_rule,
    )

    matrix = _sparse_ids_container()
    matrix_manifest = _matrix_manifest()
    matrix_offsets = _manifest_offsets(matrix_manifest)
    alpha_offset = matrix_offsets.extension_ids[_MATRIX_STAGE_ID]
    bravo_offset = matrix_offsets.extension_ids[_MATRIX_STREAM_TYPE]
    reject(
        "extension-id-adjacent-separators",
        _mutate_manifest_body(
            matrix,
            (alpha_offset + _MATRIX_STAGE_ID.index(".") + 1, b"."),
        ),
        ("extension", "identifier", "adjacent-separators"),
        "invalid_structure",
        extension_rule,
    )
    reject(
        "duplicate-extension-id",
        _mutate_manifest_body(
            matrix,
            (bravo_offset, _MATRIX_STAGE_ID.encode("ascii")),
        ),
        ("extension", "duplicate", "canonical-order"),
        "invalid_structure",
        extension_rule,
    )
    reject(
        "noncanonical-extension-order",
        _mutate_manifest_body(
            matrix,
            (alpha_offset, _MATRIX_STREAM_TYPE.encode("ascii")),
            (bravo_offset, _MATRIX_STAGE_ID.encode("ascii")),
        ),
        ("extension", "canonical-order"),
        "invalid_structure",
        extension_rule,
    )

    url_container = _specification_url_container()
    url_offsets = _manifest_offsets(_specification_url_manifest())
    url_offset = url_offsets.extension_urls[RawExtension.extension_id]
    colon_offset = _SPECIFICATION_URL.index(":")
    reject(
        "specification-url-whitespace",
        _mutate_manifest_body(
            url_container,
            (url_offset + colon_offset, b" "),
        ),
        ("extension", "specification-url", "whitespace"),
        "invalid_structure",
        extension_rule,
    )
    reject(
        "specification-url-missing-scheme-separator",
        _mutate_manifest_body(
            url_container,
            (url_offset + colon_offset, b"/"),
        ),
        ("extension", "specification-url", "scheme"),
        "invalid_structure",
        extension_rule,
    )

    encoded_matrix_manifest = _manifest_bytes(matrix)
    matrix_header = ManifestHeader.decode(
        encoded_matrix_manifest[: ManifestHeader.size]
    )
    matrix_body = encoded_matrix_manifest[ManifestHeader.size :]
    extra_id = b"zz.extra@1"
    extra_entry = extension_declaration.pack(len(extra_id), 0) + extra_id
    insertion = matrix_offsets.extensions_end - ManifestHeader.size
    unreferenced_body = matrix_body[:insertion] + extra_entry + matrix_body[insertion:]
    unreferenced_manifest = _manifest_with_body(
        encoded_matrix_manifest,
        unreferenced_body,
        extension_count=matrix_header.extension_count + 1,
    )
    reject(
        "unreferenced-extension",
        _replace_manifest(
            matrix,
            unreferenced_manifest,
            recipe_count=2,
            stream_count=2,
        ),
        ("extension", "unreferenced"),
        "invalid_structure",
        extension_rule,
    )

    recipes_start = matrix_offsets.extensions_end - ManifestHeader.size
    streams_start = matrix_offsets.streams_start - ManifestHeader.size
    zero_recipes_body = matrix_body[:recipes_start] + matrix_body[streams_start:]
    reject(
        "zero-recipes",
        _replace_manifest(
            matrix,
            _manifest_with_body(encoded_matrix_manifest, zero_recipes_body),
            recipe_count=0,
            stream_count=2,
        ),
        ("manifest", "zero-recipes"),
        "invalid_structure",
        manifest_rule,
    )
    zero_streams_body = matrix_body[:streams_start]
    reject(
        "zero-streams",
        _replace_manifest(
            matrix,
            _manifest_with_body(encoded_matrix_manifest, zero_streams_body),
            recipe_count=2,
            stream_count=0,
        ),
        ("manifest", "zero-streams"),
        "invalid_structure",
        manifest_rule,
    )

    recipe_1 = matrix_offsets.recipe_offsets[1]
    recipe_7 = matrix_offsets.recipe_offsets[7]
    stage_1 = matrix_offsets.recipe_stage_offsets[1][0]
    reject(
        "duplicate-recipe-id",
        _mutate_manifest_body(matrix, (recipe_7, struct.pack("<I", 1))),
        ("recipe", "duplicate", "canonical-order"),
        "invalid_structure",
        recipe_rule,
    )
    reject(
        "noncanonical-recipe-order",
        _mutate_manifest_body(matrix, (recipe_1, struct.pack("<I", 8))),
        ("recipe", "canonical-order"),
        "invalid_structure",
        recipe_rule,
    )
    reject(
        "recipe-reserved",
        _mutate_manifest_body(matrix, (recipe_1 + 6, struct.pack("<H", 1))),
        ("recipe", "reserved"),
        "invalid_structure",
        recipe_rule,
    )
    reject(
        "recipe-zero-stages",
        _mutate_manifest_body(matrix, (recipe_1 + 4, struct.pack("<H", 0))),
        ("recipe", "zero-stages"),
        "invalid_structure",
        recipe_rule,
    )
    reject(
        "unknown-stage-extension-index",
        _mutate_manifest_body(
            matrix,
            (stage_1, struct.pack("<I", len(matrix_manifest.extensions))),
        ),
        ("recipe", "stage", "unknown-extension-index"),
        "invalid_structure",
        recipe_rule,
    )
    reject(
        "truncated-stage-parameters",
        _mutate_manifest_body(
            matrix,
            (stage_1 + 4, struct.pack("<I", uint32.maximum)),
        ),
        ("recipe", "stage-parameters", "truncation"),
        "truncated",
        recipe_rule,
    )

    stream_2 = matrix_offsets.stream_offsets[2]
    stream_8 = matrix_offsets.stream_offsets[8]
    reject(
        "duplicate-stream-id",
        _mutate_manifest_body(matrix, (stream_8, struct.pack("<I", 2))),
        ("stream", "duplicate", "canonical-order"),
        "invalid_structure",
        stream_rule,
    )
    reject(
        "noncanonical-stream-order",
        _mutate_manifest_body(matrix, (stream_2, struct.pack("<I", 9))),
        ("stream", "canonical-order"),
        "invalid_structure",
        stream_rule,
    )
    reject(
        "unknown-stream-extension-index",
        _mutate_manifest_body(
            matrix,
            (stream_2 + 4, struct.pack("<I", len(matrix_manifest.extensions))),
        ),
        ("stream", "unknown-extension-index"),
        "invalid_structure",
        stream_rule,
    )
    reject(
        "unknown-default-recipe",
        _mutate_manifest_body(matrix, (stream_2 + 8, struct.pack("<I", 99))),
        ("stream", "unknown-default-recipe"),
        "invalid_structure",
        stream_rule,
    )
    reject(
        "truncated-stream-metadata",
        _mutate_manifest_body(
            matrix,
            (stream_2 + 12, struct.pack("<I", uint32.maximum)),
        ),
        ("stream", "metadata", "truncation"),
        "truncated",
        stream_rule,
    )
    trailing_manifest = _manifest_with_body(
        encoded_matrix_manifest,
        matrix_body + b"\x00",
    )
    reject(
        "trailing-manifest-bytes",
        _replace_manifest(
            matrix,
            trailing_manifest,
            recipe_count=2,
            stream_count=2,
        ),
        ("manifest", "trailing-bytes"),
        "invalid_structure",
        manifest_rule,
    )

    chunk_mutations: tuple[tuple[str, int, bytes, str, tuple[str, ...], bool], ...] = (
        ("chunk-magic", 0, b"NOPE", "invalid_structure", ("magic",), True),
        (
            "chunk-header-size",
            4,
            struct.pack("<H", 0),
            "invalid_structure",
            ("header-size",),
            True,
        ),
        (
            "chunk-flags",
            6,
            struct.pack("<H", 1),
            "invalid_structure",
            ("flags",),
            True,
        ),
        (
            "chunk-unknown-stream",
            8,
            struct.pack("<I", 1),
            "invalid_structure",
            ("stream-id", "unknown-stream"),
            True,
        ),
        (
            "first-sequence",
            12,
            struct.pack("<Q", 1),
            "invalid_structure",
            ("sequence", "first-chunk"),
            True,
        ),
        (
            "chunk-unknown-recipe",
            20,
            struct.pack("<I", 1),
            "invalid_structure",
            ("recipe-id", "unknown-recipe"),
            True,
        ),
        (
            "payload-crc",
            40,
            struct.pack("<I", chunk.payload_crc32 ^ 1),
            "corrupt",
            ("payload-crc",),
            True,
        ),
        (
            "chunk-header-crc",
            60,
            struct.pack("<I", 0),
            "corrupt",
            ("header-crc",),
            False,
        ),
    )
    for (
        vector_id,
        field_offset,
        replacement,
        classification,
        chunk_field_features,
        repair_crc,
    ) in chunk_mutations:
        reject(
            vector_id,
            _mutate_committed_record(
                raw,
                record_offset=chunk_offset,
                record_size=ChunkHeader.size,
                field_offset=field_offset,
                replacement=replacement,
                repair_record_crc=repair_crc,
            ),
            ("chunk", *chunk_field_features),
            classification,
            chunk_rule,
        )

    two_chunks = _write_container(
        _raw_manifest(),
        ((0, 0, 0, b"first"), (0, 1, 0, b"second")),
    )
    second_chunk_offset = _chunk_offsets(two_chunks)[1]
    reject(
        "chunk-sequence-gap",
        _mutate_committed_record(
            two_chunks,
            record_offset=second_chunk_offset,
            record_size=ChunkHeader.size,
            field_offset=12,
            replacement=struct.pack("<Q", 2),
        ),
        ("chunk", "sequence", "gap"),
        "invalid_structure",
        chunk_rule,
    )

    encoded_size_mutation = bytearray(raw)
    declared_encoded_size = chunk.encoded_size + 1
    struct.pack_into(
        "<Q",
        encoded_size_mutation,
        chunk_offset + 32,
        declared_encoded_size,
    )
    extended_payload = encoded_size_mutation[
        payload_offset : payload_offset + declared_encoded_size
    ]
    struct.pack_into(
        "<I",
        encoded_size_mutation,
        chunk_offset + 40,
        zlib.crc32(extended_payload),
    )
    _repair_record_crc(encoded_size_mutation, chunk_offset, ChunkHeader.size)
    _repair_terminal_commit(encoded_size_mutation)
    reject(
        "chunk-encoded-size",
        bytes(encoded_size_mutation),
        ("chunk", "encoded-size", "record-boundary"),
        "truncated",
        chunk_rule,
    )

    reject(
        "trailing-data",
        raw + b"trailing",
        ("terminal-commit", "trailing-data"),
        "invalid_structure",
        terminal_rule,
    )
    terminal_offset = len(raw) - TerminalCommit.size
    terminal_mutations = (
        ("terminal-magic", 0, b"NOPE", "invalid_structure", ("magic",), True),
        (
            "terminal-record-size",
            4,
            struct.pack("<H", 0),
            "invalid_structure",
            ("record-size",),
            True,
        ),
        (
            "terminal-flags",
            6,
            struct.pack("<H", 1),
            "invalid_structure",
            ("flags",),
            True,
        ),
        (
            "terminal-chunk-count",
            8,
            struct.pack("<Q", 2),
            "invalid_structure",
            ("chunk-count",),
            True,
        ),
        (
            "terminal-committed-size",
            16,
            struct.pack("<Q", 0),
            "invalid_structure",
            ("committed-size",),
            True,
        ),
        (
            "terminal-logical-size",
            24,
            struct.pack("<Q", 0),
            "invalid_structure",
            ("logical-size",),
            True,
        ),
        (
            "terminal-encoded-size",
            32,
            struct.pack("<Q", 0),
            "invalid_structure",
            ("encoded-payload-size",),
            True,
        ),
        (
            "terminal-content-hash",
            40,
            b"\x00" * 16,
            "corrupt",
            ("content-hash",),
            True,
        ),
        (
            "terminal-reserved",
            56,
            struct.pack("<I", 1),
            "invalid_structure",
            ("reserved",),
            True,
        ),
        (
            "terminal-record-crc",
            60,
            struct.pack("<I", 0),
            "corrupt",
            ("record-crc",),
            False,
        ),
    )
    for (
        vector_id,
        field_offset,
        replacement,
        classification,
        field_features,
        repair_crc,
    ) in terminal_mutations:
        mutated = bytearray(raw)
        absolute = terminal_offset + field_offset
        mutated[absolute : absolute + len(replacement)] = replacement
        if repair_crc:
            _repair_record_crc(mutated, terminal_offset, TerminalCommit.size)
        reject(
            vector_id,
            bytes(mutated),
            ("terminal-commit", *field_features),
            classification,
            terminal_rule,
        )

    logical_hash = _mutate_committed_record(
        raw,
        record_offset=chunk_offset,
        record_size=ChunkHeader.size,
        field_offset=44,
        replacement=b"\x00" * 16,
    )
    definitions.append(
        _vector(
            "logical-hash",
            "invalid",
            logical_hash,
            ("chunk", "logical-hash", "recovery"),
            (RawExtension.extension_id,),
            _recovery_rejection(stream_id=0, classification="corrupt"),
        )
    )

    logical_size = bytearray(
        _mutate_committed_record(
            raw,
            record_offset=chunk_offset,
            record_size=ChunkHeader.size,
            field_offset=24,
            replacement=struct.pack("<Q", chunk.logical_size + 1),
        )
    )
    terminal_offset = len(logical_size) - TerminalCommit.size
    struct.pack_into(
        "<Q",
        logical_size,
        terminal_offset + 24,
        chunk.logical_size + 1,
    )
    _repair_record_crc(logical_size, terminal_offset, TerminalCommit.size)
    definitions.append(
        _vector(
            "logical-size",
            "invalid",
            bytes(logical_size),
            ("chunk", "logical-size", "recovery"),
            (RawExtension.extension_id,),
            _recovery_rejection(stream_id=0, classification="decode_failure"),
        )
    )

    return tuple(definitions)


def _definitions() -> tuple[VectorDefinition, ...]:
    raw = _raw_container()
    definitions = _valid_definitions(raw) + _invalid_definitions(raw)
    ids = [definition.vector_id for definition in definitions]
    paths = [definition.path for definition in definitions]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))
    return definitions


def build_vectors() -> dict[str, bytes]:
    """Return every checked-in vector by its POSIX relative path."""
    return {definition.path: definition.encoded for definition in _definitions()}


def build_index(vectors: dict[str, bytes]) -> dict[str, object]:
    """Return the language-neutral catalog for the generated vector bytes."""
    definitions = _definitions()
    return {
        "schema_version": 2,
        "format": format_version.label,
        "encoding": "ASCII hexadecimal; whitespace is insignificant",
        "vectors": [
            {
                "id": definition.vector_id,
                "category": definition.category,
                "path": definition.path,
                "sha256": hashlib.sha256(vectors[definition.path]).hexdigest(),
                "features": list(definition.features),
                "required_extensions": list(definition.required_extensions),
                "expected": definition.expected,
            }
            for definition in definitions
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
    containers_root = CONFORMANCE_ROOT / "containers"
    for target in containers_root.rglob("*.hex"):
        relative_path = target.relative_to(CONFORMANCE_ROOT).as_posix()
        if relative_path not in vectors:
            target.unlink()
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
