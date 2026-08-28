# Resource limits

Parent: [Core API](README.md)

OBST applies one immutable local resource policy to each core operation. The
policy bounds work and allocation without changing whether container bytes are
valid under the wire format.

## Table of contents

- [Resource limits](#resource-limits)
	- [Table of contents](#table-of-contents)
	- [Configure one operation](#configure-one-operation)
	- [Default policy](#default-policy)
	- [Accounting semantics](#accounting-semantics)
	- [Policy refusal](#policy-refusal)
	- [Extension boundary](#extension-boundary)
	- [Adapter-owned limits](#adapter-owned-limits)

## Configure one operation

`ResourceLimits` is frozen and keyword-only. Core readers, writers and
[recipe execution and chunk helpers](recipes.md) accept it directly. A
packager may expose the same policy through its provider-owned request, but
that is not required by the generic Packager protocol. The
[`obst-defaults` fixed policy](../../plugins/defaults/docs/packagers/fixed.md)
is one concrete example:

```python
from obst.core import ContainerReader, ResourceLimitError, ResourceLimits

limits = ResourceLimits(
    max_manifest_bytes=8 * 1024 * 1024,
    max_chunks=100_000,
    max_total_logical_bytes=2 * 1024 * 1024 * 1024,
)
reader = ContainerReader(source, limits=limits)
```

Omitted fields retain the OBST defaults. Setting one field to `None` disables
only that local ceiling:

```python
limits = ResourceLimits(max_container_bytes=None)
```

There is no global unlimited mode. Wire field widths, framing rules and model
validity remain unconditional even when every local ceiling involved in an
operation is disabled.

## Default policy

`DEFAULT_RESOURCE_LIMITS` is the value used when an operation receives no
explicit policy.

| Resource                   | Field                           |   Default |
| -------------------------- | ------------------------------- | --------: |
| Manifest bytes             | `max_manifest_bytes`            |    16 MiB |
| Encoded bytes in one chunk | `max_encoded_chunk_bytes`       |    64 MiB |
| Logical bytes in one chunk | `max_logical_chunk_bytes`       |    64 MiB |
| One pipeline intermediate  | `max_intermediate_bytes`        |    64 MiB |
| One materialized stream    | `max_materialized_stream_bytes` |    64 MiB |
| Extension declarations     | `max_extensions`                |     4,096 |
| Recipes                    | `max_recipes`                   |     4,096 |
| Streams                    | `max_streams`                   |    65,536 |
| Stages across all recipes  | `max_total_stages`              |    65,536 |
| Stages in one recipe       | `max_stages_per_recipe`         |        64 |
| Complete container bytes   | `max_container_bytes`           |    16 GiB |
| Chunks in one container    | `max_chunks`                    |   262,144 |
| Logical bytes processed    | `max_total_logical_bytes`       |    16 GiB |
| Stage executions           | `max_stage_executions`          | 1,048,576 |

`max_container_bytes` counts bytes in the committed OBST representation. After
a valid terminal commit, a reader may request one additional byte solely to
distinguish clean endpoint exhaustion from invalid trailing data. That boundary
probe is not part of `ContainerReader.bytes_consumed` and is not charged as a
container byte.

Every non-`None` value must be an exact, non-negative `int`. Booleans are not
accepted as integers for this contract.

## Accounting semantics

Each concrete operation owns its mutable accounting. `ResourceLimits` may be
passed to several cooperating operations, but the immutable policy is shared,
not one hidden `ResourceBudget`:

- `ContainerReader` accounts structural input bytes and chunks;
- `ContainerWriter` accounts structural output, chunks and declared totals;
- `RecipeEncoder` and `RecipeDecoder` account cumulative logical bytes and
  stage executions;
- `ChunkEncoder` and `ChunkDecoder` add per-chunk checks around their recipe
  sessions; and
- `materialize_stream()` separately accounts the materialized result.

Structural inspection charges only the reader's structural work. It does not
charge logical bytes or stage executions because inspection does not decode.
Logical decoding refuses declared output and stage work before invoking a
provider.

`materialize_stream()` applies `max_materialized_stream_bytes` because it
builds one complete `bytes` result. `iter_decoded_chunks()` remains streaming
and does not inherit that materialization ceiling. A `ChunkDecoder` can
selectively decode validated chunks; skipped chunks spend no logical or stage-
execution budget.

Readers and writers use the same default declaration and chunk policy. Output
created under the default writer policy is therefore not rejected merely by
the default reader policy of the same implementation.

## Policy refusal

Crossing a local ceiling raises `ResourceLimitError`. It exposes structured
fields instead of requiring callers to parse its message:

```python
try:
    reader = ContainerReader(source, limits=limits)
except ResourceLimitError as error:
    print(error.resource, error.scope)
    print(error.maximum, error.observed, error.phase)
```

A refused container may still be structurally valid. `ResourceLimitError` is
therefore separate from `InvalidContainerError`, corruption and truncation.
The CLI reports it as `resource_limit` with exit code `10`.

## Extension boundary

[Stage encoders and decoders](../extensions/stages.md#provider-protocols)
receive `max_output_size: int | None`. Compliant providers enforce a finite
value before or while allocating output. The core then requires an exact
built-in `bytes` result and checks its size again.

The core can validate what an in-process provider returns. It cannot interrupt
a provider that blocks, loops, allocates outside the returned value or performs
side effects. Untrusted provider code needs a process or stronger isolation
boundary. The [extension registry](registry.md#keep-the-trust-boundary-explicit)
owns the in-process trust decision; resource policy does not turn arbitrary
extension code into a sandbox.

## Adapter-owned limits

Container limits do not invent filesystem or network semantics. A file adapter
may add limits for member count, one recovered file and total recovered
filesystem bytes. The concrete
[`obst-defaults` policy](../../plugins/defaults/docs/files/extraction.md#extraction-limits)
is documented with its adapter.

HTTP response sizes, deadlines and cancellation belong to the application or
transport adapter. They are not implemented by `ResourceLimits`.
