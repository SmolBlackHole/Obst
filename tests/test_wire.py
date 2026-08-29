# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import inspect
import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from obst.core.wire import (
    ChecksummedLayout,
    ChunkHeader,
    ContainerHeader,
    FixedBytes,
    ManifestHeader,
    TerminalCommit,
    UnsignedInteger,
    extension_declaration,
    format_version,
    little_endian,
    recipe_declaration,
    stage_declaration,
    stream_declaration,
    uint8,
    uint16,
    uint32,
    uint64,
)

unsigned_integers = (uint8, uint16, uint32, uint64)


@pytest.mark.parametrize(
    ("wire_type", "bits", "size", "maximum"),
    (
        (uint8, 8, 1, 2**8 - 1),
        (uint16, 16, 2, 2**16 - 1),
        (uint32, 32, 4, 2**32 - 1),
        (uint64, 64, 8, 2**64 - 1),
    ),
)
def test_unsigned_integer_descriptor_exposes_wire_bounds(
    wire_type: UnsignedInteger,
    bits: int,
    size: int,
    maximum: int,
) -> None:
    assert wire_type.bits == bits
    assert wire_type.size == size
    assert wire_type.maximum == maximum


@pytest.mark.parametrize("wire_type", unsigned_integers)
@given(data=st.data())
def test_unsigned_integer_round_trip_is_little_endian(
    wire_type: UnsignedInteger,
    data: st.DataObject,
) -> None:
    value = data.draw(st.integers(min_value=0, max_value=wire_type.maximum))

    encoded = wire_type.pack(value)

    assert encoded == value.to_bytes(wire_type.size, "little")
    assert wire_type.unpack(encoded) == value


@pytest.mark.parametrize("wire_type", unsigned_integers)
@pytest.mark.parametrize("value", (-1, True, 1.5, "1", None))
def test_unsigned_integer_rejects_invalid_values(
    wire_type: UnsignedInteger,
    value: object,
) -> None:
    error = (
        TypeError
        if not isinstance(value, int) or isinstance(value, bool)
        else ValueError
    )
    with pytest.raises(error):
        wire_type.require("field", value)


@pytest.mark.parametrize("wire_type", unsigned_integers)
def test_unsigned_integer_rejects_value_above_maximum(
    wire_type: UnsignedInteger,
) -> None:
    with pytest.raises(ValueError, match=rf"field must fit into {wire_type.name}"):
        wire_type.require("field", wire_type.maximum + 1)


@pytest.mark.parametrize(
    ("layout", "expected_format"),
    (
        (extension_declaration, "<HH"),
        (recipe_declaration, "<IHH"),
        (stage_declaration, "<II"),
        (stream_declaration, "<IIII"),
    ),
)
def test_canonical_layout_matches_frozen_struct_format(
    layout: struct.Struct,
    expected_format: str,
) -> None:
    assert layout.format == expected_format
    assert layout.size == struct.calcsize(expected_format)


def test_little_endian_composes_fixed_and_integer_fields() -> None:
    layout = little_endian(FixedBytes(3), uint16, uint64)

    assert layout.format == "<3sHQ"


def test_checksummed_layout_owns_complete_size() -> None:
    layout = ChecksummedLayout(
        prefix=little_endian(FixedBytes(4), uint16),
        record=little_endian(FixedBytes(4), uint16, uint32),
    )

    assert layout.size == layout.record.size
    assert layout.size == layout.prefix.size + uint32.size


def test_checksummed_layout_owns_crc_framing() -> None:
    layout = ChecksummedLayout(
        prefix=little_endian(FixedBytes(4), uint16),
        record=little_endian(FixedBytes(4), uint16, uint32),
    )
    values = (b"TEST", 7)

    encoded = layout.pack(*values)

    assert layout.unpack(encoded) == values
    assert layout.has_valid_crc(encoded)

    corrupted = bytearray(encoded)
    corrupted[0] ^= 0xFF
    assert not layout.has_valid_crc(corrupted)
    assert not layout.has_valid_crc(encoded[:-1])


def test_container_header_round_trip() -> None:
    record = ContainerHeader(manifest_size=123, stream_count=2, recipe_count=3)

    encoded = record.encode()

    assert len(encoded) == ContainerHeader.size == 32
    assert encoded.startswith(ContainerHeader.magic)
    assert record.version is format_version
    assert tuple(inspect.signature(ContainerHeader).parameters) == (
        "manifest_size",
        "stream_count",
        "recipe_count",
    )
    assert ContainerHeader.decode(encoded) == record


def test_manifest_header_round_trip() -> None:
    record = ManifestHeader(extension_count=4, body_size=123, body_crc32=456)

    encoded = record.encode()

    assert len(encoded) == ManifestHeader.size == 24
    assert encoded.startswith(ManifestHeader.magic)
    assert ManifestHeader.decode(encoded) == record


def test_chunk_header_round_trip() -> None:
    record = ChunkHeader(
        stream_id=1,
        sequence=2,
        recipe_id=3,
        logical_size=4,
        encoded_size=5,
        payload_crc32=6,
        logical_hash=b"l" * 16,
    )

    encoded = record.encode()

    assert len(encoded) == ChunkHeader.size == 64
    assert encoded.startswith(ChunkHeader.magic)
    assert ChunkHeader.decode(encoded) == record


def test_terminal_commit_round_trip() -> None:
    record = TerminalCommit(
        chunk_count=1,
        committed_size=2,
        logical_size=3,
        encoded_payload_size=4,
        content_hash=b"c" * 16,
    )

    encoded = record.encode()

    assert len(encoded) == TerminalCommit.size == 64
    assert encoded.startswith(TerminalCommit.magic)
    assert TerminalCommit.decode(encoded) == record


@pytest.mark.parametrize("size", (0, -1))
def test_fixed_bytes_requires_positive_width(size: int) -> None:
    with pytest.raises(ValueError, match="fixed byte width must be positive"):
        FixedBytes(size)


def test_unsigned_integer_rejects_unsupported_width() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported unsigned integer width",
    ):
        UnsignedInteger(24)
