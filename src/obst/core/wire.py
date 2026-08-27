"""Canonical scalar types and fixed records for the OBST wire format."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Buffer
from dataclasses import dataclass, field
from typing import Any, ClassVar

from obst.core.errors import (
    CorruptContainerError,
    InvalidContainerError,
    UnsupportedVersionError,
)


@dataclass(frozen=True, slots=True)
class UnsignedInteger:
    """One fixed-width little-endian unsigned integer wire type."""

    bits: int
    _layout: struct.Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            format_code = {8: "B", 16: "H", 32: "I", 64: "Q"}[self.bits]
        except KeyError as exc:
            raise ValueError("unsupported unsigned integer width") from exc
        layout = struct.Struct(f"<{format_code}")
        object.__setattr__(self, "_layout", layout)

    @property
    def name(self) -> str:
        """Return the language-neutral wire type name."""
        return f"uint{self.bits}"

    @property
    def format_code(self) -> str:
        """Return this type's standard-library struct format fragment."""
        return self._layout.format.removeprefix("<")

    @property
    def size(self) -> int:
        """Return the encoded width in bytes."""
        return self._layout.size

    @property
    def maximum(self) -> int:
        """Return the largest representable unsigned value."""
        return (1 << self.bits) - 1

    def require(self, field_name: str, value: object) -> int:
        """Return one valid integer or raise a field-specific model error."""
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{field_name} must be an integer")
        if not 0 <= value <= self.maximum:
            raise ValueError(f"{field_name} must fit into {self.name}")
        return value

    def pack(self, value: object, *, field_name: str | None = None) -> bytes:
        """Validate and encode one value."""
        checked = self.require(field_name or self.name, value)
        return self._layout.pack(checked)

    def unpack(self, data: Buffer) -> int:
        """Decode one exact-width value."""
        value = self._layout.unpack(data)[0]
        assert isinstance(value, int)
        return value


@dataclass(frozen=True, slots=True)
class FixedBytes:
    """One fixed-width opaque byte field used in a record layout."""

    size: int

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("fixed byte width must be positive")

    @property
    def format_code(self) -> str:
        """Return this field's standard-library struct format fragment."""
        return f"{self.size}s"


type WireField = UnsignedInteger | FixedBytes


@dataclass(frozen=True, slots=True)
class ChecksummedLayout:
    """A fixed record split into CRC-covered prefix and complete bytes."""

    prefix: struct.Struct
    record: struct.Struct

    @property
    def size(self) -> int:
        """Return the complete encoded record width."""
        return self.record.size

    def pack(self, *values: object) -> bytes:
        """Encode the CRC-covered fields and append their checksum."""
        prefix = self.prefix.pack(*values)
        return prefix + uint32.pack(zlib.crc32(prefix))

    def unpack(self, data: Buffer) -> tuple[Any, ...]:
        """Decode one exact complete record without exposing its checksum."""
        return self.record.unpack(data)[:-1]

    def has_valid_crc(self, data: Buffer) -> bool:
        """Return whether one exact complete record has its declared CRC32."""
        view = memoryview(data)
        if view.nbytes != self.size:
            return False
        declared_crc = uint32.unpack(view[self.prefix.size :])
        return zlib.crc32(view[: self.prefix.size]) == declared_crc


def little_endian(*fields: WireField) -> struct.Struct:
    """Build one reusable standard-layout struct from wire field descriptors."""
    return struct.Struct("<" + "".join(field.format_code for field in fields))


uint8 = UnsignedInteger(8)
uint16 = UnsignedInteger(16)
uint32 = UnsignedInteger(32)
uint64 = UnsignedInteger(64)
BLAKE2S_128_SIZE = 16


@dataclass(frozen=True, slots=True)
class FormatVersion:
    """One named OBST wire-format version."""

    major: int
    minor: int
    codename: str

    def __post_init__(self) -> None:
        uint8.require("format major", self.major)
        uint8.require("format minor", self.minor)
        if type(self.codename) is not str:
            raise TypeError("format codename must be a string")
        if not self.codename:
            raise ValueError("format codename cannot be empty")

    @property
    def numeric(self) -> tuple[int, int]:
        """Return the language-neutral numeric wire identity."""
        return self.major, self.minor

    @property
    def label(self) -> str:
        """Return the human-readable numeric and codename identity."""
        return f"{self.major}.{self.minor}-{self.codename}"


format_version = FormatVersion(major=0, minor=1, codename="apple")


def _checksummed(*fields: WireField) -> ChecksummedLayout:
    return ChecksummedLayout(
        prefix=little_endian(*fields),
        record=little_endian(*fields, uint32),
    )


_magic = FixedBytes(4)
_blake2s_128 = FixedBytes(BLAKE2S_128_SIZE)

_container_header_layout = _checksummed(
    _magic,
    uint8,
    uint8,
    uint16,
    uint32,
    uint32,
    uint32,
    uint32,
    uint32,
)
_manifest_header_layout = _checksummed(
    _magic,
    uint8,
    uint8,
    uint16,
    uint32,
    uint32,
    uint32,
)
_chunk_header_layout = _checksummed(
    _magic,
    uint16,
    uint16,
    uint32,
    uint64,
    uint32,
    uint64,
    uint64,
    uint32,
    _blake2s_128,
)
_terminal_commit_layout = _checksummed(
    _magic,
    uint16,
    uint16,
    uint64,
    uint64,
    uint64,
    uint64,
    _blake2s_128,
    uint32,
)


@dataclass(frozen=True, slots=True)
class ContainerHeader:
    """Validated fields of one current-version container header."""

    manifest_size: int
    stream_count: int
    recipe_count: int
    version: FormatVersion = format_version

    magic: ClassVar[bytes] = b"OBST"
    size: ClassVar[int] = _container_header_layout.size

    def __post_init__(self) -> None:
        uint32.require("manifest_size", self.manifest_size)
        uint32.require("stream_count", self.stream_count)
        uint32.require("recipe_count", self.recipe_count)
        _require_format_version(self.version)

    def encode(self) -> bytes:
        """Encode this header with canonical flags, reserved fields and CRC."""
        return _container_header_layout.pack(
            self.magic,
            self.version.major,
            self.version.minor,
            self.size,
            0,
            self.manifest_size,
            self.stream_count,
            self.recipe_count,
            0,
        )

    @classmethod
    def decode(cls, data: Buffer) -> ContainerHeader:
        """Decode and structurally validate one complete container header."""
        _require_record_size(data, cls.size, "container header")
        (
            magic,
            version_major,
            version_minor,
            header_size,
            flags,
            manifest_size,
            stream_count,
            recipe_count,
            reserved,
        ) = _container_header_layout.unpack(data)
        if magic != cls.magic:
            raise InvalidContainerError("invalid container magic")
        if header_size != cls.size:
            raise InvalidContainerError(
                f"unsupported container header size {header_size}"
            )
        if not _container_header_layout.has_valid_crc(data):
            raise CorruptContainerError("container header checksum mismatch")
        numeric_version = version_major, version_minor
        if numeric_version != format_version.numeric:
            raise UnsupportedVersionError("OBST", numeric_version)
        if flags != 0 or reserved != 0:
            raise InvalidContainerError(
                "container flags and reserved field must be zero"
            )
        return cls(
            manifest_size=manifest_size,
            stream_count=stream_count,
            recipe_count=recipe_count,
        )


@dataclass(frozen=True, slots=True)
class ManifestHeader:
    """Validated fields of one current-version manifest header."""

    extension_count: int
    body_size: int
    body_crc32: int

    magic: ClassVar[bytes] = b"MANF"
    size: ClassVar[int] = _manifest_header_layout.size

    def __post_init__(self) -> None:
        uint32.require("extension_count", self.extension_count)
        uint32.require("manifest body size", self.body_size)
        uint32.require("manifest body crc32", self.body_crc32)

    def encode(self) -> bytes:
        """Encode this header with the current version and its header CRC."""
        return _manifest_header_layout.pack(
            self.magic,
            format_version.major,
            format_version.minor,
            self.size,
            self.extension_count,
            self.body_size,
            self.body_crc32,
        )

    @classmethod
    def decode(cls, data: Buffer) -> ManifestHeader:
        """Decode and structurally validate one complete manifest header."""
        _require_record_size(data, cls.size, "manifest header")
        (
            magic,
            version_major,
            version_minor,
            header_size,
            extension_count,
            body_size,
            body_crc32,
        ) = _manifest_header_layout.unpack(data)
        if magic != cls.magic:
            raise InvalidContainerError("invalid manifest magic")
        if header_size != cls.size:
            raise InvalidContainerError(
                f"unsupported manifest header size {header_size}"
            )
        if not _manifest_header_layout.has_valid_crc(data):
            raise CorruptContainerError("manifest header checksum mismatch")
        numeric_version = version_major, version_minor
        if numeric_version != format_version.numeric:
            raise UnsupportedVersionError("manifest", numeric_version)
        return cls(
            extension_count=extension_count,
            body_size=body_size,
            body_crc32=body_crc32,
        )


@dataclass(frozen=True, slots=True)
class ChunkHeader:
    """Validated fields of one encoded chunk header."""

    stream_id: int
    sequence: int
    recipe_id: int
    logical_size: int
    encoded_size: int
    payload_crc32: int
    logical_hash: bytes

    magic: ClassVar[bytes] = b"CHNK"
    size: ClassVar[int] = _chunk_header_layout.size

    def __post_init__(self) -> None:
        uint32.require("stream_id", self.stream_id)
        uint64.require("sequence", self.sequence)
        uint32.require("recipe_id", self.recipe_id)
        uint64.require("logical_size", self.logical_size)
        uint64.require("encoded_size", self.encoded_size)
        uint32.require("payload_crc32", self.payload_crc32)
        _require_hash("logical hash", self.logical_hash)

    def encode(self) -> bytes:
        """Encode this header with canonical flags and its header CRC."""
        return _chunk_header_layout.pack(
            self.magic,
            self.size,
            0,
            self.stream_id,
            self.sequence,
            self.recipe_id,
            self.logical_size,
            self.encoded_size,
            self.payload_crc32,
            self.logical_hash,
        )

    @classmethod
    def decode(cls, data: Buffer) -> ChunkHeader:
        """Decode and structurally validate one complete chunk header."""
        _require_record_size(data, cls.size, "chunk header")
        (
            magic,
            header_size,
            flags,
            stream_id,
            sequence,
            recipe_id,
            logical_size,
            encoded_size,
            payload_crc32,
            logical_hash,
        ) = _chunk_header_layout.unpack(data)
        if magic != cls.magic:
            raise InvalidContainerError("invalid chunk magic")
        if header_size != cls.size:
            raise InvalidContainerError(f"unsupported chunk header size {header_size}")
        if not _chunk_header_layout.has_valid_crc(data):
            raise CorruptContainerError("chunk header checksum mismatch")
        if flags != 0:
            raise InvalidContainerError("chunk flags must be zero")
        return cls(
            stream_id=stream_id,
            sequence=sequence,
            recipe_id=recipe_id,
            logical_size=logical_size,
            encoded_size=encoded_size,
            payload_crc32=payload_crc32,
            logical_hash=logical_hash,
        )


@dataclass(frozen=True, slots=True)
class TerminalCommit:
    """Validated fields of one terminal commitment record."""

    chunk_count: int
    committed_size: int
    logical_size: int
    encoded_payload_size: int
    content_hash: bytes

    magic: ClassVar[bytes] = b"CMIT"
    size: ClassVar[int] = _terminal_commit_layout.size

    def __post_init__(self) -> None:
        uint64.require("chunk_count", self.chunk_count)
        uint64.require("committed_size", self.committed_size)
        uint64.require("logical_size", self.logical_size)
        uint64.require("encoded_payload_size", self.encoded_payload_size)
        _require_hash("terminal content hash", self.content_hash)

    def encode(self) -> bytes:
        """Encode this commitment with canonical fields and its record CRC."""
        return _terminal_commit_layout.pack(
            self.magic,
            self.size,
            0,
            self.chunk_count,
            self.committed_size,
            self.logical_size,
            self.encoded_payload_size,
            self.content_hash,
            0,
        )

    @classmethod
    def decode(cls, data: Buffer) -> TerminalCommit:
        """Decode and structurally validate one complete terminal commitment."""
        _require_record_size(data, cls.size, "terminal commit")
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
        ) = _terminal_commit_layout.unpack(data)
        if magic != cls.magic:
            raise InvalidContainerError("invalid terminal commit magic")
        if record_size != cls.size:
            raise InvalidContainerError(
                f"unsupported terminal commit size {record_size}"
            )
        if flags != 0 or reserved != 0:
            raise InvalidContainerError(
                "terminal commit flags and reserved field must be zero"
            )
        if not _terminal_commit_layout.has_valid_crc(data):
            raise CorruptContainerError("terminal commit checksum mismatch")
        return cls(
            chunk_count=chunk_count,
            committed_size=committed_size,
            logical_size=logical_size,
            encoded_payload_size=encoded_payload_size,
            content_hash=content_hash,
        )


extension_declaration = little_endian(uint16, uint16)
recipe_declaration = little_endian(uint32, uint16, uint16)
stage_declaration = little_endian(uint32, uint32)
stream_declaration = little_endian(uint32, uint32, uint32, uint32)


def _require_record_size(data: Buffer, expected: int, structure: str) -> None:
    actual = memoryview(data).nbytes
    if actual != expected:
        raise InvalidContainerError(
            f"{structure} must contain exactly {expected} bytes, got {actual}"
        )


def _require_hash(name: str, value: object) -> None:
    if type(value) is not bytes:
        raise TypeError(f"{name} must be bytes")
    if len(value) != BLAKE2S_128_SIZE:
        raise ValueError(f"{name} must contain exactly {BLAKE2S_128_SIZE} bytes")


def _require_format_version(value: object) -> None:
    if not isinstance(value, FormatVersion):
        raise TypeError("version must be a FormatVersion")
