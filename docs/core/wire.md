# Python wire mapping

Parent: [Core API](README.md)

`obst.core.wire` is the Python reference implementation's canonical mapping
from OBST wire fields to typed fixed records and declaration layouts. It keeps
format identity, widths, byte order, record sizes, CRC framing and structural
validation in one place. The language-neutral byte contract remains the
[binary format specification](../format.md).

## Table of contents

- [Python wire mapping](#python-wire-mapping)
	- [Table of contents](#table-of-contents)
	- [Responsibility and boundary](#responsibility-and-boundary)
	- [Scalar wire types](#scalar-wire-types)
	- [Record layouts](#record-layouts)
	- [Checksummed records](#checksummed-records)
	- [Reader and writer integration](#reader-and-writer-integration)
	- [Keeping the mapping honest](#keeping-the-mapping-honest)
	- [Related documentation](#related-documentation)

## Responsibility and boundary

The format specification decides field order, width, byte order, CRC coverage
and validity. `wire.py` expresses those decisions once for the Python reader,
writer and manifest codec. Call sites use each record type's own `size` instead
of maintaining parallel layouts or size constants.

The module is an implementation boundary for OBST contributors, not part of
the supported public `obst.core` import surface. Applications and extensions use the
public models and operations exported by `obst.core`. An extension also owns
the representation of its own parameter and metadata bytes; those formats do
not become core wire layouts.

## Scalar wire types

`UnsignedInteger` describes one fixed-width little-endian unsigned integer.
The module provides four reusable descriptor values:

| Descriptor |   Width | Range            | `struct` code |
| ---------- | ------: | ---------------- | ------------- |
| `uint8`    |  1 byte | `0` to `2**8-1`  | `B`           |
| `uint16`   | 2 bytes | `0` to `2**16-1` | `H`           |
| `uint32`   | 4 bytes | `0` to `2**32-1` | `I`           |
| `uint64`   | 8 bytes | `0` to `2**64-1` | `Q`           |

Each descriptor owns its name, encoded size, maximum value, validation and
single-value packing. Booleans are rejected even though Python treats `bool`
as a subclass of `int`.

`FixedBytes(size)` describes an opaque fixed-width byte field.
`little_endian()` combines integer and byte descriptors into one standard
little-endian `struct.Struct`. The lowercase names identify reusable descriptor
objects, not Python types or duplicated numeric constants.

`BLAKE2S_128_SIZE` names the 16-byte digest width shared by logical chunk hashes
and the terminal content hash. The name is algorithm-specific because both
fields use the BLAKE2s-128 contract defined by the format.

`FormatVersion` and `format_version` own the numeric and named Python identity
of the supported wire format. Runtime policies live in
[`ResourceLimits`](resources.md); the wire version is a format fact, not a
configurable limit.

## Record layouts

The module maps every fixed v0.1 record to one immutable Python record:

| Python mapping          | Representation        | Normative definition                                   |
| ----------------------- | --------------------- | ------------------------------------------------------ |
| `ContainerHeader`       | typed fixed record    | [Container header](../format.md#container-header)      |
| `ManifestHeader`        | typed fixed record    | [Manifest](../format.md#manifest)                      |
| `ChunkHeader`           | typed fixed record    | [Chunk framing](../format.md#chunk-framing)            |
| `TerminalCommit`        | typed fixed record    | [Terminal commit](../format.md#terminal-commit-record) |
| `extension_declaration` | internal plain layout | [Extension table](../format.md#extension-table)        |
| `recipe_declaration`    | internal plain layout | [Recipe entries](../format.md#recipe-entries)          |
| `stage_declaration`     | internal plain layout | [Recipe entries](../format.md#recipe-entries)          |
| `stream_declaration`    | internal plain layout | [Stream entries](../format.md#stream-entries)          |

The table names the Python mapping. The linked format sections remain the
authority for offsets, meanings, reserved values and validation rules.

## Checksummed records

Each fixed record exposes its canonical `magic` and `size`. `encode()` writes
canonical version, flags and reserved values where those fields exist, plus the
record CRC. `decode()` accepts exactly one complete record and validates its
magic, size, CRC and any version, flag or reserved fields before returning
typed semantic fields.

The record types use private `ChecksummedLayout` values. A checksummed layout
holds two standard-library layouts:

- `prefix` describes the fields covered by the trailing CRC32;
- `record` describes the complete stored record, including that CRC32.

`pack()` serializes the prefix and appends its CRC32. `unpack()` returns only
semantic fields, so record decoders do not accidentally treat the stored
checksum as model data. `has_valid_crc()` accepts only an exactly sized
complete record and validates its declared checksum.

The complete byte width is available as `ChunkHeader.size`, for example,
instead of synchronizing a separate `CHUNK_HEADER_SIZE` constant with a layout.

## Reader and writer integration

`container.py` uses the typed records for the outer header, chunks and terminal
commitment. It validates declared recipe and stream counts from
`ContainerHeader`, then reads the fixed `ManifestHeader` and validates its body
size and Extension count before requesting the variable-size manifest body.

`manifest.py` uses `ManifestHeader` and the declaration layouts while a
bounds-checked `Cursor` consumes variable-length manifest data. Its encoder
preflights the exact encoded size against the writer policy before constructing
the complete body. Model and packaging validation reuse the unsigned integer
descriptors when a value must fit a particular wire width.

This split keeps byte layout separate from I/O behavior. `wire.py` knows how a
fixed record is represented, while `io.py` owns partial reads, partial writes
and hostile stream contracts. The public `ContainerReader` and
`ContainerWriter` compose both concerns.

## Keeping the mapping honest

[`tests/test_wire.py`](../../tests/test_wire.py) checks fixed-record identities
and round trips, declaration format strings, unsigned bounds and CRC behavior.
Container, manifest, vector and sample tests exercise the records as complete
wire representations.

A change to field order, width, byte order, CRC coverage or record size changes
the format. Before the compatibility freeze, an intentional wire revision must
update the normative specification and regenerate golden vectors and samples
together with the implementation.

## Related documentation

- [Binary format specification](../format.md)
- [Structural reading](reading.md)
- [Structural writing](writing.md)
- [Runtime errors](../errors.md)
