# Structural writing

Parent: [Core API](README.md)

`ContainerWriter` serializes one final manifest and already
[encoded chunks](recipes.md#execute-one-chunk). It is deliberately lower-level
than a [packager](packaging.md): it does not choose recipes, execute stages,
split input or know where the bytes will be stored.

## Table of contents

- [Structural writing](#structural-writing)
	- [Table of contents](#table-of-contents)
	- [Write encoded chunks](#write-encoded-chunks)
	- [Resource accounting](#resource-accounting)

## Write encoded chunks

```python
from io import BytesIO

from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ContainerWriter,
    Manifest,
    ResourceAccounting,
)

target = BytesIO()
manifest = Manifest(recipes=recipes, streams=streams, extensions=extensions)
accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
writer = ContainerWriter(target, manifest, accounting=accounting)

for chunk in encoded_chunks:
    writer.write_chunk(chunk)

result = writer.finish()
container_bytes = target.getvalue()
```

The target needs only Python's structural binary `write()` operation. Partial
writes are supported. Wrong return types, no progress and progress outside the
offered buffer raise `BinaryIOContractError`.

`ContainerWriter` does not open, flush or close the endpoint. The caller owns
that lifecycle when writing directly; a selected carrier owns it when the
operation uses a streaming or transactional adapter.

Construction validates and writes the complete manifest before any chunk.
`write_chunk()` then enforces declared stream and recipe references,
per-stream sequence order and configured size limits. It calculates framing
CRCs but does not execute or validate the chunk's recipe.

`finish()` writes the terminal commit record and returns `ContainerSummary`
with the complete encoded byte count, chunk count, logical size and encoded-
payload size. `ContainerReader.summary` exposes the same facts after a complete
read. The terminal record commits to the preceding byte count, chunk count,
logical and encoded-payload totals and a BLAKE2s-128 hash of the complete
preceding representation.

The writer is `writing` after construction has published the header and
manifest. It becomes `complete` only after the entire terminal commit is
written. Any validation, resource or target failure during `write_chunk()` or
`finish()` makes it `failed`; a complete or failed writer rejects every later
write or finish attempt with `OperationStateError`. Recovery is a carrier
concern, not an invitation to append more bytes to an uncertain stream.

Use [Packaging](packaging.md) when starting from logical bytes. Use an
[output carrier](../extensions/carriers.md) when publication needs a commit and
abort lifecycle around the binary target.

## Resource accounting

`ContainerWriter(..., accounting=accounting)` applies the selected manifest,
container, chunk-count and per-chunk ceilings. It also preflights the complete
declared logical output. A cooperating `ChunkEncoder` receives the same
accountant, so pipeline and structural work remain part of one operation. The
writer proves a manifest fits before building its body and checks a complete
chunk record before publishing that record.

Local policy refusal raises `ResourceLimitError`. Wire representability remains
an independent model and format rule. The complete contract lives in
[Resource policy](resources.md).

The exact Python layouts used for these records are described in
[Python wire mapping](wire.md). The [binary format specification](../format.md)
remains authoritative for their stored bytes and validity rules.
