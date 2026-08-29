from __future__ import annotations

import hashlib
import io
import struct
import zlib
from collections.abc import Buffer, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Self, cast

import pytest

from obst.core import (
    BYTES_STREAM_TYPE,
    Chunk,
    ContainerReader,
    ContainerWriter,
    CoreResource,
    CorruptContainerError,
    ExtensionDescriptor,
    ExtensionRegistry,
    Manifest,
    MissingStageError,
    OperationStateError,
    PipelineError,
    Recipe,
    ResourceLimitError,
    ResourcePolicy,
    StageSpec,
    Stream,
    TruncatedContainerError,
    UnknownRecipeError,
    UnknownStreamError,
    UnsupportedVersionError,
    encode_chunk_once,
    inspect_container,
    iter_decoded_chunks,
    materialize_stream,
)
from obst.core.errors import InvalidContainerError
from obst.core.extensions import ExtensionKind, require_no_parameters
from obst.core.streams import ChunkDecoder, ChunkEncoder
from obst.core.wire import (
    ChunkHeader,
    ContainerHeader,
    ManifestHeader,
    TerminalCommit,
)
from tests.support_extensions import CompressionExtension as ZlibExtension
from tests.support_extensions import IdentityExtension as RawExtension
from tests.support_resources import policy as _policy

_DEFAULT_MANIFEST_CEILING = cast(int, CoreResource.MANIFEST_BYTES.default_maximum)
_DEFAULT_CHUNK_CEILING = cast(
    int,
    CoreResource.ENCODED_CHUNK_BYTES.default_maximum,
)
_DEFAULT_STREAM_CEILING = cast(int, CoreResource.STREAMS.default_maximum)
_DEFAULT_RECIPE_CEILING = cast(int, CoreResource.RECIPES.default_maximum)


@dataclass(frozen=True, slots=True)
class _HeaderMutation:
    offset: int
    replacement: bytes
    error_type: type[Exception]
    message: str
    repair_checksum: bool = True
    requires_decoding: bool = False


class _HeaderOnlyReader:
    def __init__(self, header: bytes) -> None:
        self._header = header
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        self.requested_sizes.append(size)
        if len(self.requested_sizes) > 1:
            raise AssertionError("reader attempted to consume manifest bytes")
        return self._header


class _RecordingReader:
    def __init__(self, data: bytes) -> None:
        self._source = io.BytesIO(data)
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        self.requested_sizes.append(size)
        return self._source.read(size)


class _SwitchableFailingWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.fail = False

    def write(self, data: Buffer, /) -> int:
        if self.fail:
            raise OSError("target write failed")
        view = memoryview(data)
        self.data.extend(view)
        return len(view)


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry((RawExtension(), ZlibExtension()))


def first_chunk_offset(encoded: bytes | bytearray) -> int:
    manifest_size = cast(int, struct.unpack_from("<I", encoded, 12)[0])
    return ContainerHeader.size + manifest_size


def rewrite_chunk_header_crc(encoded: bytearray, chunk_offset: int) -> None:
    crc_offset = chunk_offset + ChunkHeader.size - 4
    struct.pack_into(
        "<I",
        encoded,
        crc_offset,
        zlib.crc32(encoded[chunk_offset:crc_offset]),
    )


def rewrite_container_header_crc(encoded: bytearray) -> None:
    struct.pack_into(
        "<I",
        encoded,
        ContainerHeader.size - 4,
        zlib.crc32(encoded[: ContainerHeader.size - 4]),
    )


def terminal_commit_offset(encoded: bytes | bytearray) -> int:
    return len(encoded) - TerminalCommit.size


def rewrite_terminal_commit_crc(encoded: bytearray) -> None:
    commit_offset = terminal_commit_offset(encoded)
    crc_offset = commit_offset + TerminalCommit.size - 4
    struct.pack_into(
        "<I",
        encoded,
        crc_offset,
        zlib.crc32(encoded[commit_offset:crc_offset]),
    )


def rewrite_terminal_commit_hash(encoded: bytearray) -> None:
    commit_offset = terminal_commit_offset(encoded)
    encoded[commit_offset + 40 : commit_offset + 56] = hashlib.blake2s(
        encoded[:commit_offset],
        digest_size=16,
    ).digest()
    rewrite_terminal_commit_crc(encoded)


def raw_manifest(*, stage_id: str = RawExtension.extension_id) -> Manifest:
    return Manifest(
        recipes=(Recipe(0, (StageSpec(stage_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )


def write_container(
    manifest: Manifest,
    payload: bytes,
    *,
    registry: ExtensionRegistry | None = None,
    chunk_size: int = 64 * 1024,
) -> bytes:
    target = io.BytesIO()
    effective_registry = _stage_registry() if registry is None else registry
    encoder = ChunkEncoder(effective_registry)
    encoder.preflight(manifest.recipes)
    writer = ContainerWriter(target, manifest)
    for sequence, offset in enumerate(range(0, len(payload), chunk_size)):
        writer.write_chunk(
            encoder.encode(
                payload[offset : offset + chunk_size],
                stream_id=0,
                sequence=sequence,
                recipe=manifest.recipe(manifest.stream(0).default_recipe_id),
            )
        )
    writer.finish()
    return target.getvalue()


def _encode_for_manifest(
    manifest: Manifest,
    registry: ExtensionRegistry,
    *,
    stream_id: int,
    sequence: int,
    data: bytes,
    recipe_id: int | None = None,
) -> Chunk:
    selected_recipe_id = (
        manifest.stream(stream_id).default_recipe_id if recipe_id is None else recipe_id
    )
    return encode_chunk_once(
        data,
        stream_id=stream_id,
        sequence=sequence,
        recipe=manifest.recipe(selected_recipe_id),
        registry=registry,
    )


def test_container_reader_enforces_manifest_count_limits() -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(
            Stream(0, BYTES_STREAM_TYPE, 0),
            Stream(1, BYTES_STREAM_TYPE, 0),
        ),
    )
    encoded = write_container(manifest, b"payload")

    with pytest.raises(ResourceLimitError, match="streams"):
        ContainerReader(
            io.BytesIO(encoded),
            policy=_policy((CoreResource.STREAMS, 1)),
        )


@pytest.mark.parametrize(
    ("policy", "message"),
    (
        (_policy((CoreResource.RECIPES, 0)), "recipes"),
        (_policy((CoreResource.STREAMS, 0)), "streams"),
    ),
)
def test_container_reader_rejects_declared_counts_before_reading_manifest(
    policy: ResourcePolicy,
    message: str,
) -> None:
    encoded = write_container(raw_manifest(), b"payload")
    source = _HeaderOnlyReader(encoded[: ContainerHeader.size])

    with pytest.raises(ResourceLimitError, match=message):
        ContainerReader(source, policy=policy)

    assert source.requested_sizes == [ContainerHeader.size]


def test_extension_count_is_checked_before_manifest_body_read() -> None:
    encoded = write_container(raw_manifest(), b"payload")
    source = _RecordingReader(encoded)

    with pytest.raises(ResourceLimitError, match="extensions"):
        ContainerReader(
            source,
            policy=_policy((CoreResource.EXTENSIONS, 0)),
        )

    assert source.requested_sizes == [ContainerHeader.size, ManifestHeader.size]


@pytest.mark.parametrize("removed_bytes", [1, 5, 47, TerminalCommit.size])
def test_truncated_terminal_commit_is_detected(removed_bytes: int) -> None:
    encoded = write_container(raw_manifest(), b"payload")

    with pytest.raises(TruncatedContainerError):
        inspect_container(ContainerReader(io.BytesIO(encoded[:-removed_bytes])))


@pytest.mark.parametrize("removed_chunk_count", [1, 2])
def test_complete_chunk_suffix_removal_is_detected(
    removed_chunk_count: int,
) -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)
    chunk_record_size = ChunkHeader.size + 4
    cut_offset = first_chunk_offset(encoded) + (
        (2 - removed_chunk_count) * chunk_record_size
    )

    with pytest.raises(TruncatedContainerError, match="terminal commit"):
        inspect_container(ContainerReader(io.BytesIO(encoded[:cut_offset])))


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            _HeaderMutation(0, b"NOPE", InvalidContainerError, "container magic"),
            id="magic",
        ),
        pytest.param(
            _HeaderMutation(
                4,
                b"\x01",
                UnsupportedVersionError,
                r"OBST version 1\.1",
            ),
            id="version-major",
        ),
        pytest.param(
            _HeaderMutation(
                5,
                b"\x02",
                UnsupportedVersionError,
                r"OBST version 0\.2",
            ),
            id="version-minor",
        ),
        pytest.param(
            _HeaderMutation(
                6,
                struct.pack("<H", 0),
                InvalidContainerError,
                "container header size",
            ),
            id="header-size",
        ),
        pytest.param(
            _HeaderMutation(
                8,
                struct.pack("<I", 1),
                InvalidContainerError,
                "flags and reserved",
            ),
            id="flags",
        ),
        pytest.param(
            _HeaderMutation(
                12,
                struct.pack("<I", _DEFAULT_MANIFEST_CEILING + 1),
                ResourceLimitError,
                "manifest_bytes",
            ),
            id="manifest-size",
        ),
        pytest.param(
            _HeaderMutation(
                16,
                struct.pack("<I", _DEFAULT_STREAM_CEILING + 1),
                ResourceLimitError,
                "streams",
            ),
            id="stream-count",
        ),
        pytest.param(
            _HeaderMutation(
                20,
                struct.pack("<I", _DEFAULT_RECIPE_CEILING + 1),
                ResourceLimitError,
                "recipes",
            ),
            id="recipe-count",
        ),
        pytest.param(
            _HeaderMutation(
                24,
                struct.pack("<I", 1),
                InvalidContainerError,
                "flags and reserved",
            ),
            id="reserved",
        ),
        pytest.param(
            _HeaderMutation(
                28,
                struct.pack("<I", 0),
                CorruptContainerError,
                "container header checksum",
                repair_checksum=False,
            ),
            id="header-crc",
        ),
    ],
)
def test_container_header_mutation_matrix(mutation: _HeaderMutation) -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    encoded[mutation.offset : mutation.offset + len(mutation.replacement)] = (
        mutation.replacement
    )
    if mutation.repair_checksum:
        rewrite_container_header_crc(encoded)

    with pytest.raises(mutation.error_type, match=mutation.message):
        ContainerReader(io.BytesIO(encoded))


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            _HeaderMutation(0, b"NOPE", InvalidContainerError, "chunk magic"),
            id="magic",
        ),
        pytest.param(
            _HeaderMutation(
                4,
                struct.pack("<H", 0),
                InvalidContainerError,
                "chunk header size",
            ),
            id="header-size",
        ),
        pytest.param(
            _HeaderMutation(
                6,
                struct.pack("<H", 1),
                InvalidContainerError,
                "chunk flags",
            ),
            id="flags",
        ),
        pytest.param(
            _HeaderMutation(
                8,
                struct.pack("<I", 1),
                InvalidContainerError,
                "unknown stream",
            ),
            id="stream-id",
        ),
        pytest.param(
            _HeaderMutation(
                12,
                struct.pack("<Q", 1),
                InvalidContainerError,
                "expected chunk sequence 0",
            ),
            id="sequence",
        ),
        pytest.param(
            _HeaderMutation(
                20,
                struct.pack("<I", 1),
                InvalidContainerError,
                "unknown recipe",
            ),
            id="recipe-id",
        ),
        pytest.param(
            _HeaderMutation(
                24,
                struct.pack("<Q", _DEFAULT_CHUNK_CEILING + 1),
                ResourceLimitError,
                "logical_chunk_bytes",
            ),
            id="logical-size",
        ),
        pytest.param(
            _HeaderMutation(
                32,
                struct.pack("<Q", _DEFAULT_CHUNK_CEILING + 1),
                ResourceLimitError,
                "encoded_chunk_bytes",
            ),
            id="encoded-size",
        ),
        pytest.param(
            _HeaderMutation(
                40,
                struct.pack("<I", 0),
                CorruptContainerError,
                "payload checksum",
            ),
            id="payload-crc",
        ),
        pytest.param(
            _HeaderMutation(
                44,
                b"\x00" * 16,
                CorruptContainerError,
                "decoded chunk hash mismatch",
                requires_decoding=True,
            ),
            id="logical-hash",
        ),
        pytest.param(
            _HeaderMutation(
                ChunkHeader.size - 4,
                struct.pack("<I", 0),
                CorruptContainerError,
                "chunk header checksum",
                repair_checksum=False,
            ),
            id="header-crc",
        ),
    ],
)
def test_chunk_header_mutation_matrix(mutation: _HeaderMutation) -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    chunk_offset = first_chunk_offset(encoded)
    offset = chunk_offset + mutation.offset
    encoded[offset : offset + len(mutation.replacement)] = mutation.replacement
    if mutation.repair_checksum:
        rewrite_chunk_header_crc(encoded, chunk_offset)

    with pytest.raises(mutation.error_type, match=mutation.message):
        reader = ContainerReader(io.BytesIO(encoded))
        if mutation.requires_decoding:
            materialize_stream(reader, 0, _stage_registry())
        else:
            inspect_container(reader)


def test_corrupt_chunk_payload_is_detected_without_decoding() -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    encoded[first_chunk_offset(encoded) + ChunkHeader.size] ^= 0xFF

    with pytest.raises(CorruptContainerError, match="payload checksum"):
        inspect_container(ContainerReader(io.BytesIO(encoded)))


def test_inspection_does_not_confuse_logical_size_with_integrity() -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    chunk_offset = first_chunk_offset(encoded)
    struct.pack_into("<Q", encoded, chunk_offset + 24, 8)
    rewrite_chunk_header_crc(encoded, chunk_offset)
    struct.pack_into("<Q", encoded, terminal_commit_offset(encoded) + 24, 8)
    rewrite_terminal_commit_hash(encoded)

    inspection = inspect_container(ContainerReader(io.BytesIO(encoded)))
    assert inspection.chunk_count == 1
    assert inspection.logical_size == 8
    assert inspection.encoded_payload_size == len(b"payload")
    assert inspection.streams[0].logical_size == 8

    with pytest.raises(PipelineError, match="decoded size mismatch"):
        materialize_stream(ContainerReader(io.BytesIO(encoded)), 0, _stage_registry())


def test_corrupt_manifest_is_detected() -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    encoded[ContainerHeader.size + ManifestHeader.size] ^= 0x01

    with pytest.raises(CorruptContainerError, match="manifest body checksum"):
        ContainerReader(io.BytesIO(encoded))


def test_unknown_stage_keeps_container_inspectable() -> None:
    stage = _IdentityStage()
    registry = ExtensionRegistry(
        (
            RawExtension(),
            ZlibExtension(),
            stage,
        )
    )
    encoded = write_container(
        raw_manifest(stage_id=_IdentityStage.extension_id),
        b"payload",
        registry=registry,
    )

    structural_reader = ContainerReader(io.BytesIO(encoded))
    chunks = tuple(structural_reader.iter_chunks())
    inspection = inspect_container(ContainerReader(io.BytesIO(encoded)))

    assert [chunk.encoded_payload for chunk in chunks] == [b"payload"]
    assert structural_reader.bytes_consumed == len(encoded)
    assert inspection.missing_required_stages == (_IdentityStage.extension_id,)
    assert not inspection.required_decoders_available
    with pytest.raises(MissingStageError, match=_IdentityStage.extension_id):
        materialize_stream(ContainerReader(io.BytesIO(encoded)), 0, ExtensionRegistry())


def test_bytes_stream_is_a_core_contract_without_registry_state() -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0, b"preserve even if nonconforming"),),
    )
    target = io.BytesIO()
    ContainerWriter(target, manifest).finish()
    registry = ExtensionRegistry()

    inspection = inspect_container(ContainerReader(io.BytesIO(target.getvalue())))

    assert registry.get_descriptor(BYTES_STREAM_TYPE) is None
    assert inspection.manifest.streams[0].metadata == b"preserve even if nonconforming"
    assert inspection.streams[0].metadata is None


def test_reader_tracks_bytes_consumed_by_its_own_session() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)
    reader = ContainerReader(io.BytesIO(encoded))

    assert reader.bytes_consumed == first_chunk_offset(encoded)

    chunks = reader.iter_chunks()
    first = next(chunks)
    assert first.sequence == 0
    assert first.encoded_payload == b"abcd"
    assert reader.bytes_consumed == first_chunk_offset(encoded) + ChunkHeader.size + 4

    assert [chunk.sequence for chunk in chunks] == [1]
    assert reader.bytes_consumed == len(encoded)


def test_completed_reader_writer_and_inspection_share_one_summary() -> None:
    manifest = raw_manifest()
    registry = _stage_registry()
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest)
    writer.write_chunk(
        _encode_for_manifest(
            manifest,
            registry,
            stream_id=0,
            sequence=0,
            data=b"payload",
        )
    )

    written = writer.finish()
    reader = ContainerReader(io.BytesIO(target.getvalue()))
    with pytest.raises(OperationStateError, match="ready state"):
        _ = reader.summary
    tuple(reader.iter_chunks())
    inspected = inspect_container(ContainerReader(io.BytesIO(target.getvalue())))

    assert written.logical_size == 7
    assert written.encoded_payload_size == 7
    assert reader.summary == written
    assert inspected.summary == written


def test_manifest_preflight_validates_all_recipe_parameters_before_encoding() -> None:
    target = io.BytesIO()
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(ZlibExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )

    with pytest.raises(PipelineError, match="compression-level"):
        ChunkEncoder(_stage_registry()).preflight(manifest.recipes)

    assert target.getvalue() == b""


def test_encoder_only_writer_and_decoder_only_reader_interoperate() -> None:
    writer_registry = ExtensionRegistry((_IdentityEncoderExtension(),))
    encoded = write_container(
        raw_manifest(stage_id=_IdentityStage.extension_id),
        b"payload",
        registry=writer_registry,
    )

    reader_registry = ExtensionRegistry((_IdentityDecoderExtension(),))
    reader = ContainerReader(io.BytesIO(encoded))

    assert materialize_stream(reader, 0, registry=reader_registry) == b"payload"


def test_decode_rejects_wrong_implementation_registered_under_same_id() -> None:
    payload = b"same length, wrong bytes"
    writer_registry = ExtensionRegistry((_XorStage(),))
    reader_registry = ExtensionRegistry((_WrongXorStage(),))
    encoded = write_container(
        raw_manifest(stage_id=_XorStage.extension_id),
        payload,
        registry=writer_registry,
    )

    assert inspect_container(
        ContainerReader(io.BytesIO(encoded)),
        registry=reader_registry,
    ).required_decoders_available
    with pytest.raises(CorruptContainerError, match="decoded chunk hash mismatch"):
        materialize_stream(
            ContainerReader(io.BytesIO(encoded)),
            0,
            registry=reader_registry,
        )


def test_decode_rejects_tampered_logical_hash_after_inspection() -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    chunk_offset = first_chunk_offset(encoded)
    encoded[chunk_offset + 44] ^= 0xFF
    rewrite_chunk_header_crc(encoded, chunk_offset)
    rewrite_terminal_commit_hash(encoded)

    assert inspect_container(ContainerReader(io.BytesIO(encoded))).chunk_count == 1
    with pytest.raises(CorruptContainerError, match="decoded chunk hash mismatch"):
        materialize_stream(ContainerReader(io.BytesIO(encoded)), 0, _stage_registry())


def test_declared_sizes_are_checked_before_payload_read() -> None:
    encoded = write_container(raw_manifest(), b"payload")
    policy = _policy((CoreResource.ENCODED_CHUNK_BYTES, 3))

    with pytest.raises(ResourceLimitError, match="encoded_chunk_bytes"):
        inspect_container(ContainerReader(io.BytesIO(encoded), policy=policy))


def test_container_byte_budget_accepts_exact_size_and_refuses_one_byte_less() -> None:
    encoded = write_container(raw_manifest(), b"payload")

    inspection = inspect_container(
        ContainerReader(
            io.BytesIO(encoded),
            policy=_policy((CoreResource.CONTAINER_BYTES, len(encoded))),
        )
    )
    assert inspection.encoded_size == len(encoded)

    with pytest.raises(ResourceLimitError) as error:
        inspect_container(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.CONTAINER_BYTES, len(encoded) - 1)),
            )
        )
    assert error.value.resource is CoreResource.CONTAINER_BYTES


def test_trailing_probe_does_not_charge_committed_container_budget() -> None:
    valid = write_container(raw_manifest(), b"payload")
    source = io.BytesIO(valid + b"x")
    reader = ContainerReader(
        source,
        policy=_policy((CoreResource.CONTAINER_BYTES, len(valid))),
    )

    with pytest.raises(InvalidContainerError, match="trailing bytes"):
        inspect_container(reader)

    assert reader.bytes_consumed == len(valid)
    assert source.tell() == len(valid) + 1


def test_chunk_count_budget_accepts_exact_count_and_refuses_next_chunk() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)

    assert (
        inspect_container(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.CHUNKS, 2)),
            )
        ).chunk_count
        == 2
    )

    with pytest.raises(ResourceLimitError) as error:
        inspect_container(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.CHUNKS, 1)),
            )
        )
    assert error.value.resource is CoreResource.CHUNKS
    assert error.value.observed == 2


def test_inspection_does_not_charge_logical_recovery_budget() -> None:
    encoded = write_container(raw_manifest(), b"payload")
    refused_policy = _policy((CoreResource.LOGICAL_BYTES, 0))

    assert (
        inspect_container(
            ContainerReader(io.BytesIO(encoded), policy=refused_policy)
        ).chunk_count
        == 1
    )

    assert (
        materialize_stream(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.LOGICAL_BYTES, 7)),
            ),
            0,
            _stage_registry(),
        )
        == b"payload"
    )

    with pytest.raises(ResourceLimitError) as error:
        materialize_stream(
            ContainerReader(io.BytesIO(encoded), policy=refused_policy),
            0,
            _stage_registry(),
        )
    assert error.value.resource is CoreResource.LOGICAL_BYTES


def test_successfully_consumed_reader_is_complete_and_single_use() -> None:
    encoded = write_container(raw_manifest(), b"payload")
    reader = ContainerReader(io.BytesIO(encoded))

    inspect_container(reader)

    with pytest.raises(OperationStateError, match="complete state") as error:
        materialize_stream(reader, 0, _stage_registry())
    assert error.value.operation == "read container chunks"
    assert error.value.state == "complete"


def test_structural_reader_failure_is_terminal() -> None:
    encoded = write_container(raw_manifest(), b"payload")
    reader = ContainerReader(io.BytesIO(encoded[:-1]))

    with pytest.raises(TruncatedContainerError):
        tuple(reader.iter_chunks())

    with pytest.raises(OperationStateError, match="failed state") as error:
        tuple(reader.iter_chunks())
    assert error.value.state == "failed"


def test_abandoned_reader_iteration_cannot_be_restarted() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)
    reader = ContainerReader(io.BytesIO(encoded))
    chunks = cast(Generator[Chunk], reader.iter_chunks())

    assert next(chunks).sequence == 0
    with pytest.raises(OperationStateError, match="consuming state") as consuming:
        tuple(reader.iter_chunks())
    assert consuming.value.state == "consuming"

    chunks.close()
    with pytest.raises(OperationStateError, match="failed state") as failed:
        tuple(reader.iter_chunks())
    assert failed.value.state == "failed"


def test_materialize_stream_enforces_combined_output_limit() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)

    assert (
        materialize_stream(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.MATERIALIZED_STREAM_BYTES, 8)),
            ),
            0,
            _stage_registry(),
        )
        == b"abcdefgh"
    )
    with pytest.raises(ResourceLimitError, match="materialized_stream_bytes"):
        materialize_stream(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.MATERIALIZED_STREAM_BYTES, 7)),
            ),
            0,
            _stage_registry(),
        )


def test_materialize_stream_reports_unknown_selection_before_consuming() -> None:
    encoded = write_container(raw_manifest(), b"payload")
    reader = ContainerReader(io.BytesIO(encoded))

    with pytest.raises(UnknownStreamError) as error:
        materialize_stream(reader, 99, _stage_registry())

    assert error.value.stream_id == 99
    assert tuple(reader.iter_chunks())


def test_iter_decoded_chunks_is_bounded_streaming_api() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)

    decoded = list(
        iter_decoded_chunks(
            ContainerReader(io.BytesIO(encoded)),
            _stage_registry(),
        )
    )

    assert [(chunk.sequence, payload) for chunk, payload in decoded] == [
        (0, b"abcd"),
        (1, b"efgh"),
    ]
    assert (
        decoded[0][0].logical_hash == hashlib.blake2s(b"abcd", digest_size=16).digest()
    )


def test_chunk_decoder_needs_only_manifest_index_and_validated_chunks() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)
    reader = ContainerReader(io.BytesIO(encoded))
    chunks = tuple(reader.iter_chunks())
    decoder = ChunkDecoder(
        reader.index,
        _stage_registry(),
        policy=reader.policy,
    )

    recovered = b"".join(decoder.decode(chunk) for chunk in chunks)

    assert all(chunk.logical_size <= 4 for chunk in chunks)
    assert recovered == b"abcdefgh"


def test_chunk_encoder_reuses_one_recipe_binding_across_chunks() -> None:
    stage = _CountingIdentityStage()
    registry = ExtensionRegistry((stage,))
    recipe = Recipe(0, (StageSpec(stage.extension_id),))
    encoder = ChunkEncoder(registry)

    first = encoder.encode(b"first", stream_id=0, sequence=0, recipe=recipe)
    second = encoder.encode(b"second", stream_id=0, sequence=1, recipe=recipe)

    assert first.encoded_payload == b"first"
    assert second.encoded_payload == b"second"
    assert stage.encoder_bind_count == 1


def test_materialize_stream_skips_unselected_chunks_without_decode_budget() -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(
            Stream(0, BYTES_STREAM_TYPE, 0),
            Stream(1, BYTES_STREAM_TYPE, 0),
        ),
    )
    registry = _stage_registry()
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest)
    writer.write_chunk(
        _encode_for_manifest(
            manifest,
            registry,
            stream_id=0,
            sequence=0,
            data=b"skip",
        )
    )
    writer.write_chunk(
        _encode_for_manifest(
            manifest,
            registry,
            stream_id=1,
            sequence=0,
            data=b"keep",
        )
    )
    writer.finish()

    assert (
        materialize_stream(
            ContainerReader(
                io.BytesIO(target.getvalue()),
                policy=_policy((CoreResource.STAGE_EXECUTIONS, 1)),
            ),
            1,
            registry,
        )
        == b"keep"
    )


def test_recovery_stage_budget_spans_all_chunks() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)

    with pytest.raises(ResourceLimitError) as error:
        list(
            iter_decoded_chunks(
                ContainerReader(
                    io.BytesIO(encoded),
                    policy=_policy((CoreResource.STAGE_EXECUTIONS, 1)),
                ),
                _stage_registry(),
            )
        )

    assert error.value.resource is CoreResource.STAGE_EXECUTIONS
    assert error.value.observed == 2


def test_chunk_recipe_override_uses_the_selected_recipe() -> None:
    manifest = Manifest(
        recipes=(
            Recipe(0, (StageSpec(RawExtension.extension_id),)),
            Recipe(1, (StageSpec(ZlibExtension.extension_id, b"\x09"),)),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    registry = _stage_registry()
    writer = ContainerWriter(target, manifest)

    written = _encode_for_manifest(
        manifest,
        registry,
        stream_id=0,
        sequence=0,
        data=b"compress me" * 32,
        recipe_id=1,
    )
    writer.write_chunk(written)
    writer.finish()
    decoded = list(
        iter_decoded_chunks(
            ContainerReader(io.BytesIO(target.getvalue())),
            registry,
        )
    )

    assert written.recipe_id == 1
    assert [(chunk.recipe_id, payload) for chunk, payload in decoded] == [
        (1, b"compress me" * 32)
    ]


def test_writer_serializes_preencoded_chunk_without_a_stage_registry() -> None:
    manifest = raw_manifest(stage_id=_IdentityStage.extension_id)
    prepared = Chunk(
        stream_id=0,
        sequence=0,
        recipe_id=0,
        logical_size=7,
        logical_hash=hashlib.blake2s(b"logical", digest_size=16).digest(),
        encoded_payload=b"already encoded",
    )
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest)

    writer.write_chunk(prepared)
    result = writer.finish()

    recovered = tuple(ContainerReader(io.BytesIO(target.getvalue())).iter_chunks())
    assert recovered == (prepared,)
    assert result.encoded_size == len(target.getvalue())
    assert result.chunk_count == 1
    assert not hasattr(writer, "registry")


def test_writer_completion_is_single_use() -> None:
    target = io.BytesIO()
    manifest = raw_manifest()
    registry = _stage_registry()
    writer = ContainerWriter(target, manifest)
    writer.write_chunk(
        _encode_for_manifest(
            manifest,
            registry,
            stream_id=0,
            sequence=0,
            data=b"payload",
        )
    )

    result = writer.finish()

    assert result.encoded_size == len(target.getvalue())
    assert result.chunk_count == 1
    with pytest.raises(OperationStateError, match="complete state") as finish_error:
        writer.finish()
    assert finish_error.value.state == "complete"
    with pytest.raises(OperationStateError, match="complete state") as chunk_error:
        writer.write_chunk(
            Chunk(
                0,
                1,
                0,
                0,
                hashlib.blake2s(b"", digest_size=16).digest(),
                b"",
            )
        )
    assert chunk_error.value.state == "complete"


def test_target_write_failure_leaves_writer_terminally_failed() -> None:
    target = _SwitchableFailingWriter()
    manifest = raw_manifest()
    writer = ContainerWriter(target, manifest)
    chunk = _encode_for_manifest(
        manifest,
        _stage_registry(),
        stream_id=0,
        sequence=0,
        data=b"payload",
    )
    target.fail = True

    with pytest.raises(OSError, match="target write failed"):
        writer.write_chunk(chunk)

    with pytest.raises(OperationStateError, match="failed state") as write_error:
        writer.write_chunk(chunk)
    assert write_error.value.state == "failed"
    with pytest.raises(OperationStateError, match="failed state") as finish_error:
        writer.finish()
    assert finish_error.value.state == "failed"


def test_failed_finish_cannot_be_retried() -> None:
    target = _SwitchableFailingWriter()
    writer = ContainerWriter(target, raw_manifest())
    target.fail = True

    with pytest.raises(OSError, match="target write failed"):
        writer.finish()

    with pytest.raises(OperationStateError, match="failed state") as error:
        writer.finish()
    assert error.value.state == "failed"


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            _HeaderMutation(0, b"NOPE", InvalidContainerError, "chunk magic"),
            id="magic",
        ),
        pytest.param(
            _HeaderMutation(
                4,
                struct.pack("<H", 0),
                InvalidContainerError,
                "terminal commit size",
            ),
            id="record-size",
        ),
        pytest.param(
            _HeaderMutation(
                6,
                struct.pack("<H", 1),
                InvalidContainerError,
                "flags and reserved",
            ),
            id="flags",
        ),
        pytest.param(
            _HeaderMutation(
                8,
                struct.pack("<Q", 2),
                InvalidContainerError,
                "declares 2 chunks",
            ),
            id="chunk-count",
        ),
        pytest.param(
            _HeaderMutation(
                16,
                struct.pack("<Q", 0),
                InvalidContainerError,
                "committed bytes",
            ),
            id="committed-size",
        ),
        pytest.param(
            _HeaderMutation(
                24,
                struct.pack("<Q", 0),
                InvalidContainerError,
                "logical bytes",
            ),
            id="logical-size",
        ),
        pytest.param(
            _HeaderMutation(
                32,
                struct.pack("<Q", 0),
                InvalidContainerError,
                "encoded payload size",
            ),
            id="encoded-payload-size",
        ),
        pytest.param(
            _HeaderMutation(
                40,
                b"\x00" * 16,
                CorruptContainerError,
                "content hash",
            ),
            id="content-hash",
        ),
        pytest.param(
            _HeaderMutation(
                56,
                struct.pack("<I", 1),
                InvalidContainerError,
                "flags and reserved",
            ),
            id="reserved",
        ),
        pytest.param(
            _HeaderMutation(
                TerminalCommit.size - 4,
                struct.pack("<I", 0),
                CorruptContainerError,
                "terminal commit checksum",
                repair_checksum=False,
            ),
            id="record-crc",
        ),
    ],
)
def test_terminal_commit_mutation_matrix(mutation: _HeaderMutation) -> None:
    encoded = bytearray(write_container(raw_manifest(), b"payload"))
    offset = terminal_commit_offset(encoded) + mutation.offset
    encoded[offset : offset + len(mutation.replacement)] = mutation.replacement
    if mutation.repair_checksum:
        rewrite_terminal_commit_crc(encoded)

    with pytest.raises(mutation.error_type, match=mutation.message):
        inspect_container(ContainerReader(io.BytesIO(encoded)))


def test_terminal_commit_rejects_trailing_bytes() -> None:
    encoded = write_container(raw_manifest(), b"payload") + b"trailing"

    with pytest.raises(InvalidContainerError, match="trailing bytes"):
        inspect_container(ContainerReader(io.BytesIO(encoded)))


def test_terminal_commit_fields_bind_the_complete_preceding_container() -> None:
    encoded = write_container(raw_manifest(), b"abcdefgh", chunk_size=4)
    commit_offset = terminal_commit_offset(encoded)
    (
        magic,
        record_size,
        flags,
        chunk_count,
        committed_size,
        logical_size,
        encoded_payload_size,
        content_hash,
        reserved,
        record_crc32,
    ) = struct.unpack_from("<4sHHQQQQ16sII", encoded, commit_offset)

    assert magic == b"CMIT"
    assert record_size == TerminalCommit.size
    assert flags == reserved == 0
    assert chunk_count == 2
    assert committed_size == commit_offset
    assert logical_size == encoded_payload_size == 8
    assert (
        content_hash
        == hashlib.blake2s(encoded[:commit_offset], digest_size=16).digest()
    )
    assert record_crc32 == zlib.crc32(encoded[commit_offset:-4])


@pytest.mark.parametrize(
    ("chunk", "error_type", "message"),
    [
        (
            Chunk(1, 0, 0, 1, hashlib.blake2s(b"x", digest_size=16).digest(), b"x"),
            UnknownStreamError,
            "unknown stream",
        ),
        (
            Chunk(0, 0, 1, 1, hashlib.blake2s(b"x", digest_size=16).digest(), b"x"),
            UnknownRecipeError,
            "unknown recipe",
        ),
        (
            Chunk(0, 1, 0, 1, hashlib.blake2s(b"x", digest_size=16).digest(), b"x"),
            ValueError,
            "expected chunk sequence 0",
        ),
    ],
)
def test_writer_rejects_invalid_chunk_references_and_sequences(
    chunk: Chunk,
    error_type: type[Exception],
    message: str,
) -> None:
    target = io.BytesIO()
    writer = ContainerWriter(target, raw_manifest())
    header_size = len(target.getvalue())

    with pytest.raises(error_type, match=message):
        writer.write_chunk(chunk)

    assert len(target.getvalue()) == header_size


@pytest.mark.parametrize(
    ("policy", "chunk", "message"),
    [
        (
            _policy((CoreResource.LOGICAL_CHUNK_BYTES, 3)),
            Chunk(
                0,
                0,
                0,
                4,
                hashlib.blake2s(b"abcd", digest_size=16).digest(),
                b"x",
            ),
            "logical_chunk_bytes",
        ),
        (
            _policy((CoreResource.ENCODED_CHUNK_BYTES, 3)),
            Chunk(
                0,
                0,
                0,
                1,
                hashlib.blake2s(b"x", digest_size=16).digest(),
                b"abcd",
            ),
            "encoded_chunk_bytes",
        ),
    ],
)
def test_writer_rejects_chunks_above_its_size_limits(
    policy: ResourcePolicy,
    chunk: Chunk,
    message: str,
) -> None:
    target = io.BytesIO()
    writer = ContainerWriter(target, raw_manifest(), policy=policy)
    header_size = len(target.getvalue())

    with pytest.raises(ResourceLimitError, match=message):
        writer.write_chunk(chunk)

    assert len(target.getvalue()) == header_size


def test_writer_rejects_oversized_manifest_before_publishing_bytes() -> None:
    target = io.BytesIO()

    with pytest.raises(ResourceLimitError, match="manifest_bytes"):
        ContainerWriter(
            target,
            raw_manifest(),
            policy=_policy((CoreResource.MANIFEST_BYTES, 0)),
        )

    assert target.getvalue() == b""


def test_writer_reserves_terminal_commit_before_publishing_header() -> None:
    manifest = raw_manifest()
    complete = write_container(manifest, b"")
    target = io.BytesIO()

    writer = ContainerWriter(
        target,
        manifest,
        policy=_policy((CoreResource.CONTAINER_BYTES, len(complete))),
    )
    summary = writer.finish()

    assert target.getvalue() == complete
    assert summary.encoded_size == len(complete)

    refused_target = io.BytesIO()
    with pytest.raises(ResourceLimitError) as error:
        ContainerWriter(
            refused_target,
            manifest,
            policy=_policy((CoreResource.CONTAINER_BYTES, len(complete) - 1)),
        )
    assert error.value.resource is CoreResource.CONTAINER_BYTES
    assert error.value.observed == len(complete)
    assert refused_target.getvalue() == b""


def test_writer_reserves_terminal_commit_before_publishing_chunk() -> None:
    manifest = raw_manifest()
    registry = _stage_registry()
    chunk = _encode_for_manifest(
        manifest,
        registry,
        stream_id=0,
        sequence=0,
        data=b"payload",
    )
    complete = write_container(manifest, b"payload", registry=registry)
    target = io.BytesIO()
    writer = ContainerWriter(
        target,
        manifest,
        policy=_policy((CoreResource.CONTAINER_BYTES, len(complete) - 1)),
    )
    prefix = target.getvalue()

    with pytest.raises(ResourceLimitError) as error:
        writer.write_chunk(chunk)

    assert error.value.resource is CoreResource.CONTAINER_BYTES
    assert error.value.observed == len(complete)
    assert target.getvalue() == prefix


def test_writer_refuses_chunk_count_before_publishing_rejected_chunk() -> None:
    target = io.BytesIO()
    manifest = raw_manifest()
    writer = ContainerWriter(
        target,
        manifest,
        policy=_policy((CoreResource.CHUNKS, 0)),
    )
    size_before_chunk = len(target.getvalue())

    with pytest.raises(ResourceLimitError) as error:
        writer.write_chunk(
            _encode_for_manifest(
                manifest,
                _stage_registry(),
                stream_id=0,
                sequence=0,
                data=b"payload",
            )
        )

    assert error.value.resource is CoreResource.CHUNKS
    assert len(target.getvalue()) == size_before_chunk


def test_writer_preflight_refuses_known_chunk_work_without_mutating_state() -> None:
    target = io.BytesIO()
    manifest = raw_manifest()
    writer = ContainerWriter(
        target,
        manifest,
        policy=_policy((CoreResource.LOGICAL_BYTES, 3)),
    )
    size_before_chunk = len(target.getvalue())

    with pytest.raises(ResourceLimitError) as error:
        writer.preflight_chunk(4)

    assert error.value.resource is CoreResource.LOGICAL_BYTES
    assert len(target.getvalue()) == size_before_chunk
    writer.preflight_chunk(3)
    writer.write_chunk(
        _encode_for_manifest(
            manifest,
            _stage_registry(),
            stream_id=0,
            sequence=0,
            data=b"abc",
        )
    )


def test_writer_preflights_cumulative_terminal_totals_before_chunk_output() -> None:
    target = io.BytesIO()
    manifest = raw_manifest()
    writer = ContainerWriter(
        target,
        manifest,
        policy=_policy(
            (CoreResource.LOGICAL_CHUNK_BYTES, None),
            (CoreResource.LOGICAL_BYTES, None),
        ),
    )
    maximum = (1 << 64) - 1
    digest = hashlib.blake2s(b"", digest_size=16).digest()
    writer.write_chunk(Chunk(0, 0, 0, maximum, digest, b""))
    size_before_rejected_chunk = len(target.getvalue())

    with pytest.raises(ValueError, match="logical_size must fit into uint64"):
        writer.write_chunk(Chunk(0, 1, 0, maximum, digest, b""))

    assert len(target.getvalue()) == size_before_rejected_chunk


def test_chunk_size_limit_accepts_boundary_and_rejects_larger_value() -> None:
    encoded = write_container(raw_manifest(), b"abcd")

    assert (
        materialize_stream(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy(
                    (CoreResource.ENCODED_CHUNK_BYTES, 5),
                    (CoreResource.LOGICAL_CHUNK_BYTES, 5),
                ),
            ),
            0,
            _stage_registry(),
        )
        == b"abcd"
    )
    assert (
        materialize_stream(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy(
                    (CoreResource.ENCODED_CHUNK_BYTES, 4),
                    (CoreResource.LOGICAL_CHUNK_BYTES, 4),
                ),
            ),
            0,
            _stage_registry(),
        )
        == b"abcd"
    )
    with pytest.raises(ResourceLimitError, match="logical_chunk_bytes"):
        inspect_container(
            ContainerReader(
                io.BytesIO(encoded),
                policy=_policy((CoreResource.LOGICAL_CHUNK_BYTES, 3)),
            )
        )


def test_container_round_trip_through_real_file(tmp_path: Path) -> None:
    path = tmp_path / "sample.obst"
    payload = bytes(range(256)) * 4

    with path.open("wb") as target:
        manifest = raw_manifest()
        registry = _stage_registry()
        writer = ContainerWriter(target, manifest)
        for sequence, offset in enumerate(range(0, len(payload), 127)):
            writer.write_chunk(
                _encode_for_manifest(
                    manifest,
                    registry,
                    stream_id=0,
                    sequence=sequence,
                    data=payload[offset : offset + 127],
                )
            )
        writer.finish()
    with path.open("rb") as source:
        decoded = materialize_stream(ContainerReader(source), 0, registry)

    assert decoded == payload


def test_value_objects_reject_mutable_bytes_and_collections() -> None:
    mutable = bytearray(b"abc")
    mutable_bytes = cast(bytes, mutable)
    mutable_stages = cast(
        tuple[StageSpec, ...],
        [StageSpec(RawExtension.extension_id)],
    )
    mutable_recipes = cast(
        tuple[Recipe, ...],
        [Recipe(0, (StageSpec(RawExtension.extension_id),))],
    )
    mutable_streams = cast(tuple[Stream, ...], [Stream(0, BYTES_STREAM_TYPE, 0)])

    with pytest.raises(TypeError, match="stage parameters must be bytes"):
        StageSpec(RawExtension.extension_id, mutable_bytes)
    with pytest.raises(TypeError, match="stream metadata must be bytes"):
        Stream(0, BYTES_STREAM_TYPE, 0, mutable_bytes)
    with pytest.raises(TypeError, match="encoded payload must be bytes"):
        Chunk(
            0,
            0,
            0,
            3,
            hashlib.blake2s(b"abc", digest_size=16).digest(),
            mutable_bytes,
        )
    with pytest.raises(TypeError, match="logical hash must be bytes"):
        Chunk(0, 0, 0, 3, mutable_bytes, b"abc")
    with pytest.raises(ValueError, match="exactly 16 bytes"):
        Chunk(0, 0, 0, 3, b"too short", b"abc")
    with pytest.raises(TypeError, match="recipe stages must be a tuple"):
        Recipe(0, mutable_stages)
    with pytest.raises(TypeError, match="manifest recipes must be a tuple"):
        Manifest(mutable_recipes, (Stream(0, BYTES_STREAM_TYPE, 0),))
    with pytest.raises(TypeError, match="manifest streams must be a tuple"):
        Manifest(
            (Recipe(0, (StageSpec(RawExtension.extension_id),)),),
            mutable_streams,
        )


class _IdentityBoundStage:
    extension_id = "org.example/identity@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def _bind(self, parameters: bytes) -> None:
        require_no_parameters(self.extension_id, parameters)

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        if max_output_size is not None and len(data) > max_output_size:
            raise ValueError("test stage output limit exceeded")
        return data

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        if max_output_size is not None and len(data) > max_output_size:
            raise ValueError("test stage output limit exceeded")
        return data


class _IdentityEncoderExtension(_IdentityBoundStage):
    def bind_encoder(self, parameters: bytes, /) -> Self:
        self._bind(parameters)
        return self


class _IdentityDecoderExtension(_IdentityBoundStage):
    def bind_decoder(self, parameters: bytes, /) -> Self:
        self._bind(parameters)
        return self


class _IdentityStage(_IdentityEncoderExtension, _IdentityDecoderExtension):
    pass


class _CountingIdentityStage(_IdentityStage):
    def __init__(self) -> None:
        self.encoder_bind_count = 0

    def bind_encoder(self, parameters: bytes, /) -> Self:
        self.encoder_bind_count += 1
        return super().bind_encoder(parameters)


class _XorStage:
    extension_id = "org.example/xor-integrity@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

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
        return bytes(value ^ 0xFF for value in data)

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        assert max_output_size is None or len(data) <= max_output_size
        return bytes(value ^ 0xFF for value in data)


class _WrongXorStage(_XorStage):
    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        assert max_output_size is None or len(data) <= max_output_size
        return data
