"""Core structural reader and writer for the OBST v0 wire format."""

from __future__ import annotations

import hashlib
import zlib
from collections.abc import Buffer, Iterator
from dataclasses import dataclass
from enum import Enum

from obst.core.errors import (
    CorruptContainerError,
    InvalidContainerError,
    OperationStateError,
    TruncatedContainerError,
    UnknownRecipeError,
)
from obst.core.io import (
    BinaryReader,
    BinaryWriter,
    read_exact,
    validate_read_result,
    validate_write_result,
    write_all,
)
from obst.core.manifest import (
    ManifestIndex,
    decode_manifest_parts,
    encode_manifest,
    validate_manifest_counts,
    validate_manifest_header,
)
from obst.core.model import Chunk, Manifest
from obst.core.resource_accounting import CoreResource, ResourceAccounting
from obst.core.wire import (
    BLAKE2S_128_SIZE,
    ChunkHeader,
    ContainerHeader,
    FormatVersion,
    ManifestHeader,
    TerminalCommit,
    uint64,
)


@dataclass(frozen=True, slots=True)
class ContainerSummary:
    """Final accounting shared by every fully consumed container operation."""

    encoded_size: int
    chunk_count: int
    logical_size: int
    encoded_payload_size: int


class _LifecycleState(Enum):
    READY = "ready"
    CONSUMING = "consuming"
    WRITING = "writing"
    COMPLETE = "complete"
    FAILED = "failed"


class ContainerWriter:
    """Serialize one final manifest and wire-ready encoded chunks."""

    def __init__(
        self,
        target: BinaryWriter,
        manifest: Manifest,
        *,
        accounting: ResourceAccounting,
    ) -> None:
        if type(accounting) is not ResourceAccounting:
            raise TypeError("container writer accounting must be ResourceAccounting")
        self.manifest = manifest
        self.index = ManifestIndex(manifest)
        self.accounting = accounting
        self._next_sequences = {stream.stream_id: 0 for stream in self.manifest.streams}
        self._target = _CountingWriter(target, self.accounting)
        self._chunk_count = 0
        self._logical_size = 0
        self._encoded_payload_size = 0
        self._state = _LifecycleState.WRITING
        manifest_bytes = encode_manifest(
            self.manifest,
            accounting=self.accounting,
        )
        self._write_container_header(manifest_bytes)

    def preflight_chunk(self, logical_size: int, /) -> None:
        """Refuse known chunk work before a caller encodes its payload."""
        self._require_writing("preflight chunk")
        if type(logical_size) is not int:
            raise TypeError("logical chunk size must be an integer")
        if logical_size < 0:
            raise ValueError("logical chunk size must be non-negative")
        self._check_chunk_capacity(logical_size)

    def write_chunk(self, chunk: Chunk) -> None:
        """Write one already encoded chunk without executing its recipe."""
        self._require_writing("write chunk")
        try:
            self.index.stream(chunk.stream_id)
            self.index.recipe(chunk.recipe_id)
            expected_sequence = self._next_sequences[chunk.stream_id]
            if chunk.sequence != expected_sequence:
                raise ValueError(
                    f"stream {chunk.stream_id} expected chunk sequence "
                    f"{expected_sequence}, got {chunk.sequence}"
                )
            self._check_chunk_capacity(chunk.logical_size)
            self.accounting.record(
                CoreResource.ENCODED_CHUNK_BYTES,
                chunk.encoded_size,
                scope=f"stream {chunk.stream_id} chunk {chunk.sequence}",
                phase="container_write",
            )
            header = ChunkHeader(
                stream_id=chunk.stream_id,
                sequence=chunk.sequence,
                recipe_id=chunk.recipe_id,
                logical_size=chunk.logical_size,
                encoded_size=chunk.encoded_size,
                payload_crc32=zlib.crc32(chunk.encoded_payload),
                logical_hash=chunk.logical_hash,
            ).encode()
            self._preflight_terminal_totals(
                chunk,
                added_container_bytes=len(header) + chunk.encoded_size,
            )
            self._require_container_capacity(
                len(header) + chunk.encoded_size + TerminalCommit.size
            )
            self.accounting.record(
                CoreResource.LOGICAL_CHUNK_BYTES,
                chunk.logical_size,
                scope=f"stream {chunk.stream_id} chunk {chunk.sequence}",
                phase="container_write",
            )
            self.accounting.record(
                CoreResource.CHUNKS,
                1,
                scope="container",
                phase="container_write",
            )
            write_all(self._target, header)
            write_all(self._target, chunk.encoded_payload)
            self._next_sequences[chunk.stream_id] = expected_sequence + 1
            self._chunk_count += 1
            self._logical_size += chunk.logical_size
            self._encoded_payload_size += chunk.encoded_size
        except BaseException:
            self._state = _LifecycleState.FAILED
            raise

    def finish(self) -> ContainerSummary:
        """Complete the session and return final structural accounting."""
        self._require_writing("finish container write")
        try:
            self._write_terminal_commit()
        except BaseException:
            self._state = _LifecycleState.FAILED
            raise
        self._state = _LifecycleState.COMPLETE
        return ContainerSummary(
            encoded_size=self._target.bytes_written,
            chunk_count=self._chunk_count,
            logical_size=self._logical_size,
            encoded_payload_size=self._encoded_payload_size,
        )

    def _require_writing(self, operation: str) -> None:
        if self._state is not _LifecycleState.WRITING:
            raise OperationStateError(operation, self._state.value)

    def _write_container_header(self, manifest_bytes: bytes) -> None:
        header = ContainerHeader(
            manifest_size=len(manifest_bytes),
            stream_count=len(self.manifest.streams),
            recipe_count=len(self.manifest.recipes),
        ).encode()
        self._require_container_capacity(
            len(header) + len(manifest_bytes) + TerminalCommit.size
        )
        write_all(self._target, header)
        write_all(self._target, manifest_bytes)

    def _write_terminal_commit(self) -> None:
        record = TerminalCommit(
            chunk_count=self._chunk_count,
            committed_size=self._target.bytes_written,
            logical_size=self._logical_size,
            encoded_payload_size=self._encoded_payload_size,
            content_hash=self._target.content_hash,
        ).encode()
        self._require_container_capacity(len(record))
        write_all(self._target, record)

    def _require_container_capacity(self, amount: int) -> None:
        self.accounting.check(
            CoreResource.CONTAINER_BYTES,
            self._target.bytes_written + amount,
            scope="container",
            phase="container_write",
        )

    def _check_chunk_capacity(self, logical_size: int) -> None:
        scope = f"container chunk {self._chunk_count}"
        self.accounting.check(
            CoreResource.LOGICAL_CHUNK_BYTES,
            logical_size,
            scope=scope,
            phase="container_write",
        )
        self.accounting.check(
            CoreResource.CHUNKS,
            self.accounting.current(CoreResource.CHUNKS) + 1,
            scope="container",
            phase="container_write",
        )
        self.accounting.check(
            CoreResource.LOGICAL_BYTES,
            self._logical_size + logical_size,
            scope="container",
            phase="container_write",
        )

    def _preflight_terminal_totals(
        self,
        chunk: Chunk,
        *,
        added_container_bytes: int,
    ) -> None:
        uint64.require("chunk_count", self._chunk_count + 1)
        uint64.require(
            "committed_size",
            self._target.bytes_written + added_container_bytes,
        )
        uint64.require("logical_size", self._logical_size + chunk.logical_size)
        uint64.require(
            "encoded_payload_size",
            self._encoded_payload_size + chunk.encoded_size,
        )


class ContainerReader:
    """Parse one OBST byte stream into validated, still-encoded chunks."""

    def __init__(
        self,
        source: BinaryReader,
        *,
        accounting: ResourceAccounting,
    ) -> None:
        if type(accounting) is not ResourceAccounting:
            raise TypeError("container reader accounting must be ResourceAccounting")
        self.accounting = accounting
        self._source = _CountingReader(source, self.accounting)
        self.version, self.manifest, self.manifest_size = self._read_container_header()
        self.index = ManifestIndex(self.manifest)
        self._next_sequences = {stream.stream_id: 0 for stream in self.manifest.streams}
        self._chunk_count = 0
        self._logical_size = 0
        self._encoded_payload_size = 0
        self._state = _LifecycleState.READY

    @property
    def bytes_consumed(self) -> int:
        """Return the number of encoded bytes consumed from the source."""
        return self._source.bytes_read

    @property
    def summary(self) -> ContainerSummary:
        """Return final accounting after the terminal commit has been consumed."""
        if self._state is not _LifecycleState.COMPLETE:
            raise OperationStateError("read container summary", self._state.value)
        return ContainerSummary(
            encoded_size=self._source.bytes_read,
            chunk_count=self._chunk_count,
            logical_size=self._logical_size,
            encoded_payload_size=self._encoded_payload_size,
        )

    def iter_chunks(self) -> Iterator[Chunk]:
        """Yield structurally and integrity-validated encoded chunks once."""
        if self._state is not _LifecycleState.READY:
            raise OperationStateError("read container chunks", self._state.value)
        self._state = _LifecycleState.CONSUMING
        try:
            while True:
                record_start = self._source.bytes_read
                committed_hash = self._source.content_hash
                self._require_container_capacity(ChunkHeader.size)
                header = read_exact(
                    self._source,
                    ChunkHeader.size,
                    structure="chunk or terminal commit record",
                    allow_clean_eof=True,
                )
                if header is None:
                    raise TruncatedContainerError(
                        "terminal commit record",
                        expected=TerminalCommit.size,
                        actual=0,
                    )
                if header[:4] == TerminalCommit.magic:
                    self._validate_terminal_commit(
                        header,
                        committed_size=record_start,
                        committed_hash=committed_hash,
                    )
                    if self._source.read_boundary_probe():
                        raise InvalidContainerError(
                            "trailing bytes after terminal commit record"
                        )
                    self._state = _LifecycleState.COMPLETE
                    return
                chunk = self._parse_chunk_header(header)
                self._require_container_capacity(chunk.encoded_size)
                payload = read_exact(
                    self._source,
                    chunk.encoded_size,
                    structure="chunk payload",
                )
                assert payload is not None
                if zlib.crc32(payload) != chunk.payload_crc32:
                    raise CorruptContainerError("chunk payload checksum mismatch")
                parsed = Chunk(
                    stream_id=chunk.stream_id,
                    sequence=chunk.sequence,
                    recipe_id=chunk.recipe_id,
                    logical_size=chunk.logical_size,
                    logical_hash=chunk.logical_hash,
                    encoded_payload=payload,
                )
                self._chunk_count += 1
                self._logical_size += parsed.logical_size
                self._encoded_payload_size += parsed.encoded_size
                yield parsed
        finally:
            if self._state is _LifecycleState.CONSUMING:
                self._state = _LifecycleState.FAILED

    def _read_container_header(self) -> tuple[FormatVersion, Manifest, int]:
        self._require_container_capacity(ContainerHeader.size)
        header = read_exact(
            self._source, ContainerHeader.size, structure="container header"
        )
        assert header is not None
        parsed = ContainerHeader.decode(header)
        self.accounting.record(
            CoreResource.MANIFEST_BYTES,
            parsed.manifest_size,
            scope="manifest",
            phase="container_read",
        )
        validate_manifest_counts(
            recipe_count=parsed.recipe_count,
            stream_count=parsed.stream_count,
            accounting=self.accounting,
        )
        self._require_container_capacity(parsed.manifest_size)
        if parsed.manifest_size < ManifestHeader.size:
            raise InvalidContainerError("manifest is shorter than its fixed header")
        manifest_header_bytes = read_exact(
            self._source,
            ManifestHeader.size,
            structure="manifest header",
        )
        assert manifest_header_bytes is not None
        manifest_header = ManifestHeader.decode(manifest_header_bytes)
        validate_manifest_header(
            manifest_header,
            manifest_size=parsed.manifest_size,
            accounting=self.accounting,
            phase="container_read",
        )
        manifest_body = read_exact(
            self._source,
            manifest_header.body_size,
            structure="manifest body",
        )
        assert manifest_body is not None
        manifest = decode_manifest_parts(
            manifest_header,
            manifest_body,
            recipe_count=parsed.recipe_count,
            stream_count=parsed.stream_count,
            accounting=self.accounting,
        )
        return parsed.version, manifest, parsed.manifest_size

    def _parse_chunk_header(self, header: bytes) -> ChunkHeader:
        parsed = ChunkHeader.decode(header)
        scope = f"stream {parsed.stream_id} chunk {parsed.sequence}"
        self.accounting.record(
            CoreResource.ENCODED_CHUNK_BYTES,
            parsed.encoded_size,
            scope=scope,
            phase="container_read",
        )
        self.accounting.record(
            CoreResource.LOGICAL_CHUNK_BYTES,
            parsed.logical_size,
            scope=scope,
            phase="container_read",
        )
        if parsed.stream_id not in self._next_sequences:
            raise InvalidContainerError(
                f"chunk references unknown stream {parsed.stream_id}"
            )
        try:
            self.index.recipe(parsed.recipe_id)
        except UnknownRecipeError:
            raise InvalidContainerError(
                f"chunk references unknown recipe {parsed.recipe_id}"
            ) from None
        expected_sequence = self._next_sequences[parsed.stream_id]
        if parsed.sequence != expected_sequence:
            raise InvalidContainerError(
                f"stream {parsed.stream_id} expected chunk sequence "
                f"{expected_sequence}, got {parsed.sequence}"
            )
        self.accounting.record(
            CoreResource.CHUNKS,
            1,
            scope="container",
            phase="container_read",
        )
        self._next_sequences[parsed.stream_id] = parsed.sequence + 1
        return parsed

    def _require_container_capacity(self, amount: int) -> None:
        self.accounting.check(
            CoreResource.CONTAINER_BYTES,
            self._source.bytes_read + amount,
            scope="container",
            phase="container_read",
        )

    def _validate_terminal_commit(
        self,
        record: bytes,
        *,
        committed_size: int,
        committed_hash: bytes,
    ) -> None:
        commit = TerminalCommit.decode(record)
        if commit.chunk_count != self._chunk_count:
            raise InvalidContainerError(
                f"terminal commit declares {commit.chunk_count} chunks, "
                f"observed {self._chunk_count}"
            )
        if commit.committed_size != committed_size:
            raise InvalidContainerError(
                f"terminal commit declares {commit.committed_size} committed "
                f"bytes, observed {committed_size}"
            )
        if commit.logical_size != self._logical_size:
            raise InvalidContainerError(
                f"terminal commit declares {commit.logical_size} logical bytes, "
                f"observed {self._logical_size}"
            )
        if commit.encoded_payload_size != self._encoded_payload_size:
            raise InvalidContainerError(
                "terminal commit encoded payload size does not match observed chunks"
            )
        if commit.content_hash != committed_hash:
            raise CorruptContainerError("terminal commit content hash mismatch")


class _CountingReader:
    def __init__(self, source: BinaryReader, accounting: ResourceAccounting) -> None:
        self._source = source
        self._accounting = accounting
        self.bytes_read = 0
        self._content_hasher = hashlib.blake2s(digest_size=BLAKE2S_128_SIZE)

    @property
    def content_hash(self) -> bytes:
        return self._content_hasher.digest()

    def read(self, size: int = -1, /) -> bytes:
        data = validate_read_result(self._source.read(size), requested=size)
        self._accounting.record(
            CoreResource.CONTAINER_BYTES,
            len(data),
            scope="container",
            phase="container_read",
        )
        self.bytes_read += len(data)
        self._content_hasher.update(data)
        return data

    def read_boundary_probe(self) -> bytes:
        """Probe beyond the committed representation without charging it."""
        return validate_read_result(self._source.read(1), requested=1)


class _CountingWriter:
    def __init__(self, target: BinaryWriter, accounting: ResourceAccounting) -> None:
        self._target = target
        self._accounting = accounting
        self.bytes_written = 0
        self._content_hasher = hashlib.blake2s(digest_size=BLAKE2S_128_SIZE)

    @property
    def content_hash(self) -> bytes:
        return self._content_hasher.digest()

    def write(self, data: Buffer, /) -> int:
        view = memoryview(data)
        written = validate_write_result(
            self._target.write(data),
            offered=len(view),
        )
        self._accounting.record(
            CoreResource.CONTAINER_BYTES,
            written,
            scope="container",
            phase="container_write",
        )
        self.bytes_written += written
        self._content_hasher.update(view[:written])
        return written
