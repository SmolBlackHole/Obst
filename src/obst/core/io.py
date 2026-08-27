"""Public minimal binary I/O contracts used by the OBST core."""

from __future__ import annotations

import struct
from collections.abc import Buffer
from dataclasses import dataclass
from io import Reader, Writer
from typing import cast

from obst.core.errors import (
    BinaryIOContractError,
    InvalidContainerError,
    TruncatedContainerError,
)

type BinaryReader = Reader[bytes]
type BinaryWriter = Writer[Buffer]


@dataclass(slots=True)
class Cursor:
    """Bounds-checked cursor over an already size-limited byte string."""

    data: bytes
    offset: int = 0

    def take(self, size: int, *, field: str) -> bytes:
        if size < 0:
            raise InvalidContainerError(f"negative size for {field}")
        end = self.offset + size
        if end > len(self.data):
            raise TruncatedContainerError(
                field,
                expected=size,
                actual=max(len(self.data) - self.offset, 0),
            )
        value = self.data[self.offset : end]
        self.offset = end
        return value

    def unpack(self, layout: struct.Struct, *, field: str) -> tuple[int, ...]:
        return layout.unpack(self.take(layout.size, field=field))

    def ensure_finished(self, *, structure: str) -> None:
        if self.offset != len(self.data):
            raise InvalidContainerError(f"trailing bytes in {structure}")


def write_all(target: BinaryWriter, data: bytes) -> None:
    """Write all bytes, supporting targets that accept partial writes."""
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        offered = len(view) - offset
        result = cast(object, target.write(view[offset:]))
        written = validate_write_result(result, offered=offered)
        offset += written


def read_exact(
    source: BinaryReader,
    size: int,
    *,
    structure: str,
    allow_clean_eof: bool = False,
) -> bytes | None:
    """Read exactly ``size`` bytes or report a truncated structure."""
    if size < 0:
        raise InvalidContainerError(f"negative size for {structure}")
    result = bytearray(size)
    offset = 0

    while offset < size:
        requested = size - offset
        chunk = validate_read_result(
            cast(object, source.read(requested)),
            requested=requested,
        )
        if not chunk:
            if allow_clean_eof and offset == 0:
                return None
            raise TruncatedContainerError(
                structure,
                expected=size,
                actual=offset,
            )
        end = offset + len(chunk)
        result[offset:end] = chunk
        offset = end

    return bytes(result)


def validate_read_result(result: object, *, requested: int) -> bytes:
    """Validate one result from the public minimal binary reader contract."""
    if type(result) is not bytes:
        raise BinaryIOContractError("reader", "read() must return exact bytes")
    data = result
    if requested >= 0 and len(data) > requested:
        raise BinaryIOContractError(
            "reader",
            f"read({requested}) returned {len(data)} bytes",
        )
    return data


def validate_write_result(result: object, *, offered: int) -> int:
    """Validate one result from the public minimal binary writer contract."""
    if type(result) is not int:
        raise BinaryIOContractError(
            "writer",
            "write() must return an exact integer",
        )
    written = result
    if not 1 <= written <= offered:
        raise BinaryIOContractError(
            "writer",
            f"write() accepted {offered} bytes but reported {written}",
        )
    return written
