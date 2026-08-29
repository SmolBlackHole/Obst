# Reading and decoding

Parent: [Core API](README.md)

`ContainerReader` parses one OBST byte stream into a validated
[manifest](../format.md#manifest) and a single-consumption sequence of
still-encoded chunks.

## Table of contents

- [Reading and decoding](#reading-and-decoding)
	- [Table of contents](#table-of-contents)
	- [Structural reading](#structural-reading)
	- [Logical decoding](#logical-decoding)
		- [Selective chunk decoding](#selective-chunk-decoding)
	- [Resource accounting](#resource-accounting)

## Structural reading

```python
from io import BytesIO

from obst.core import DEFAULT_RESOURCE_POLICY, ContainerReader, ResourceAccounting

accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
reader = ContainerReader(BytesIO(container_bytes), accounting=accounting)
print(reader.version.label)
print(reader.manifest.streams)

for chunk in reader.iter_chunks():
    print(chunk.stream_id, chunk.sequence, chunk.encoded_size)

summary = reader.summary
print(summary.encoded_size, summary.chunk_count)
```

The source needs only Python's structural binary `read()` operation. It does
not need a path, seek support or a filesystem. A `BytesIO`, socket wrapper,
database BLOB stream or object-store response can satisfy the same boundary.
`ContainerReader` neither opens nor closes that endpoint. A caller may own it
directly, or a selected carrier may bind and release the surrounding input
session.

Construction reads and validates the container header and complete manifest.
`reader.version` is a `FormatVersion`; its `numeric` property contains the two
wire values and its `label` adds the reference codename for human output.
`iter_chunks()` then validates chunk framing, references, sequence numbers,
declared size limits, header CRCs, encoded payload CRCs and the terminal
commitment. It never executes a recipe.

A reader is `ready` after construction and becomes `consuming` when chunk
iteration starts. Reaching a valid terminal commit and clean EOF makes it
`complete`. A structural failure makes it `failed`; closing an unfinished
iterator also fails the reader. While an unfinished iterator remains open the
reader stays `consuming`. Every state except `ready` rejects another
`iter_chunks()` call with `OperationStateError`.

Individual chunks are available before the terminal record arrives. The
operation proves container completeness only when the iterator is exhausted
without error. A transactional consumer may process chunks incrementally but
must delay its own commit until then.

After clean exhaustion, `reader.summary` returns the shared `ContainerSummary`
with complete encoded size, chunk count, logical size and encoded-payload size.
Reading it before completion raises `OperationStateError`.

## Logical decoding

Decoding is a separate operation because it requires an explicitly composed
[extension registry](registry.md) containing trusted local
[stage providers](../extensions/stages.md#provider-protocols):

```python
from io import BytesIO

from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ContainerReader,
    ExtensionRegistry,
    ResourceAccounting,
    materialize_stream,
)


def recover_stream(
    container_bytes: bytes,
    registry: ExtensionRegistry,
) -> bytes:
    accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
    reader = ContainerReader(BytesIO(container_bytes), accounting=accounting)
    return materialize_stream(reader, stream_id=0, registry=registry)
```

`iter_decoded_chunks()` yields each encoded `Chunk` together with its recovered
logical bytes in physical order. `materialize_stream()` instead consumes the
complete container and materializes one selected stream, bounded by
`CoreResource.MATERIALIZED_STREAM_BYTES` in the selected policy.

Direct recipe and chunk helpers are documented under
[Recipe and chunk execution](recipes.md).

Every decoded chunk is checked against its declared logical size and
BLAKE2s-128 hash. A missing decoder raises `MissingStageError`; invalid stage
payloads raise `PipelineError`; a logical hash mismatch raises
`CorruptContainerError`.

### Selective chunk decoding

`ChunkDecoder` binds trusted stage providers lazily against one immutable
`ManifestIndex`. An adapter can inspect each encoded chunk, enforce its own
domain policy and only then spend logical recovery and stage-execution budget:

```python
from obst.core import ChunkDecoder

decoder = ChunkDecoder(reader.index, registry, accounting=reader.accounting)

for chunk in reader.iter_chunks():
    require_application_capacity(chunk.logical_size)
    logical_bytes = decoder.decode(chunk)
    consume(chunk.stream_id, logical_bytes)
```

The reader and decoder share one operation accountant. Structural reading and
logical recovery record different resources into that same state. Skipping a
chunk still consumes structural input but invokes no decoder and records no
logical bytes or Stage executions.

`reader.index` is created once from the validated manifest. A caller that
already has a `Manifest` can construct `ManifestIndex(manifest)` directly, so
indexed or non-reader adapters can feed the same `ChunkDecoder` contract.

The [runtime error reference](../errors.md) explains why unavailable
capabilities, invalid stage payloads and corrupted logical bytes are separate
failure classes.

## Resource accounting

The selected `ResourcePolicy` bounds manifest size and counts, container bytes,
chunks, encoded and logical chunk sizes, pipeline work, recovered logical bytes
and materialized stream size. `ResourceAccounting` retains this operation's
totals and peaks. Structural inspection records only resources it consumes; it
does not record logical recovery or Stage executions.

Crossing a local ceiling raises `ResourceLimitError`, not
`InvalidContainerError`. A container refused by local policy may still be valid
under the wire format. [Resource policy](resources.md) owns the defaults,
override rules and exact accounting scopes.

The Python representation of fixed fields and records is described in
[Python wire mapping](wire.md). The language-neutral validity rules remain in
the [binary format specification](../format.md).
