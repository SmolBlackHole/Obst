# Stream profiles

Parent: [Extension system](README.md)

A stream profile gives recovered logical bytes application meaning. It owns a
versioned stream-type ID, metadata bytes and the rules for interpreting the
logical byte sequence. Profiles do not choose recipes, chunking, carriers or
transport.

## Table of contents

- [Stream profiles](#stream-profiles)
	- [Table of contents](#table-of-contents)
	- [Profile boundary](#profile-boundary)
	- [Self-describing profile objects](#self-describing-profile-objects)
	- [Typed metadata codecs](#typed-metadata-codecs)
	- [Optional metadata interpretation](#optional-metadata-interpretation)
	- [Byte recovery versus semantic recovery](#byte-recovery-versus-semantic-recovery)
	- [First-party stream contracts](#first-party-stream-contracts)

## Profile boundary

The core treats a stream type as a versioned ID plus opaque metadata and
logical bytes. It defines optional typed codecs for metadata, but not a
universal codec for logical stream contents. Application code decides how
values become logical chunks and how recovered bytes become rows, images or
other domain values.

A registered profile adds local descriptive information and may add an
optional metadata interpreter for inspection. It cannot alter authoritative
metadata, recover payload bytes, choose a recipe or publish output.

## Self-describing profile objects

Application code serializes values to logical bytes. A profile object supplies
its canonical identity, descriptor and whichever metadata authoring, decoding
or inspection capabilities it implements:

> [!WARNING]
> **Executable documentation:** The following Python block runs during tests
> with the current process privileges. It is not sandboxed.

```python
import json
from dataclasses import dataclass

from obst.core import (
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistry,
    InspectionField,
    InspectionInterpretation,
)


@dataclass(frozen=True, slots=True)
class TableMetadata:
    table: str


class TableExtension:
    extension_id = "org.example/table@1"
    kind = ExtensionKind.STREAM_PROFILE
    descriptor = ExtensionDescriptor(
        display_name="Table",
        summary="Application-owned table metadata and row bytes.",
        specification_url="https://example.org/obst/table-v1",
    )

    def encode_metadata(self, value: TableMetadata, /) -> bytes:
        return json.dumps({"table": value.table}, separators=(",", ":")).encode()

    def decode_metadata(self, metadata: bytes, /) -> TableMetadata:
        document = json.loads(metadata)
        table = document["table"]
        if type(table) is not str or not table:
            raise ValueError("table must be a non-empty string")
        return TableMetadata(table)

    def interpret_metadata(
        self,
        metadata: bytes,
        /,
    ) -> InspectionInterpretation:
        try:
            value = self.decode_metadata(metadata)
        except (KeyError, TypeError, ValueError) as exc:
            return InspectionInterpretation(
                error=f"invalid table metadata: {exc}"
            )
        return InspectionInterpretation(
            label=value.table,
            fields=(InspectionField("table", value.table),),
        )

tables = TableExtension()
registry = ExtensionRegistry((tables,))
metadata = tables.encode_metadata(TableMetadata("measurements"))
assert tables.decode_metadata(metadata) == TableMetadata("measurements")
```

The host registers the same object it uses to author metadata. There is no
profile assembly wrapper or separately registered interpreter. The one
extension object owns all 3 metadata directions.

## Typed metadata codecs

`StreamMetadataEncoder[T]` and `StreamMetadataDecoder[T]` are optional generic
core protocols. They standardize how a host locates metadata authoring and
decoding without prescribing `T`. The versioned stream contract owns that
local value type and its mapping to authoritative bytes.

The registry exposes the directions independently through
`get_stream_metadata_encoder()` and `get_stream_metadata_decoder()`. This
allows an authoring-only or decoding-only provider under one ID. The type is
erased at registry lookup; a caller that selects a known contract casts the
provider to that contract's documented value type before invoking it.

Application adapters may define narrower optional capabilities outside the
core. The [file adapter](files.md), for example, recognizes `FileSourceProfile`
and `FileMaterializer`. It resolves them by exact stream-profile ID and permits
at most one provider for each capability under that ID. These protocols remain
distinct from generic metadata codecs because a regular-file source or
materializer makes additional filesystem promises.

## Optional metadata interpretation

The registry advertises an extension's optional `interpret_metadata()`
capability but does not execute it during registration. Inspection invokes it
only when the host permits that profile ID through an explicit
[`InspectionInterpretationPolicy`](../core/inspection.md#optional-interpretation).

Inspection fields use exact built-in `str`, `int`, `bool` or `None` values and
unique string names. Labels and errors are exact non-empty strings when
present. Raw metadata remains authoritative when no interpreter exists or an
interpreter returns an interpretation error. Raised exceptions and invalid
returns stop inspection with `ExtensionContractError` and preserve the
original cause.

## Byte recovery versus semantic recovery

A registry may contain every stage decoder needed to reconstruct a stream but
no profile capable of interpreting its record layout:

```text
logical bytes recoverable: yes
stream semantics understood: no
```

That distinction is intentional. The core recovers bytes. Profile and
application code decides whether those bytes become rows, images, tensors or
something much less reasonable.

## First-party stream contracts

| Stream type    | Meaning                                   | Normative contract                     | Python integration         |
| -------------- | ----------------------------------------- | -------------------------------------- | -------------------------- |
| `obst.bytes@1` | Opaque bytes with empty metadata          | [Bytes](../contracts/streams/bytes.md) | Core contract              |
| `obst.file@1`  | Portable basename and exact file contents | [File](../contracts/streams/file.md)   | [Portable files](files.md) |

`obst.bytes@1` is the sole core stream contract and needs no registry entry.
The installable `obst-defaults` plugin supplies `FileExtension` as an ordinary
extension using the same registry boundary as third-party profiles.
