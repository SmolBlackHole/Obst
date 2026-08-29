# Resource policy

Parent: [Core API](README.md)

OBST applies one immutable `ResourcePolicy` to each operation. The policy
bounds local work and allocation. It does not change the wire format and it
does not make an otherwise invalid container valid.

## Table of contents

- [Resource policy](#resource-policy)
	- [Table of contents](#table-of-contents)
	- [The public model](#the-public-model)
	- [Select ceilings for an operation](#select-ceilings-for-an-operation)
	- [Core resources and defaults](#core-resources-and-defaults)
	- [Accounting and refusal](#accounting-and-refusal)
	- [Plugins and isolation](#plugins-and-isolation)

## The public model

The resource API has five layers:

```text
ResourceDefinition  stable ID, display unit, default ceiling and summary
ResourceKind       typed identity and default ceiling
LimitProfile       named overrides
ResourceCatalog    resources and inert profiles available to one runtime
ResourcePolicy     one profile resolved over one catalog
```

`CoreResource` is the closed set measured by the Core runtime. Plugins may
define their own `ResourceKind` enum and publish those definitions through a
[`ResourceContribution`](../extensions/plugins.md#resource-contributions).

Resource identities are typed. `CoreResource.CHUNKS` is not equal to the raw
string `"chunks"`; `str(CoreResource.CHUNKS)` is its canonical serialized ID.
Core IDs are short. Plugin-owned IDs are qualified by the responsible
Extension ID, for example `obst.file@1/archive_members`.

Every definition declares a typed `ResourceUnit`: `COUNT` or `BYTES`. Human
tools can therefore render `16.0 GiB` without guessing from an identifier,
while machine-readable output keeps the exact integer. Plugins use the same
public type for their resources.

## Select ceilings for an operation

A profile contains only overrides. Every omitted resource falls back to the
default declared by its `ResourceKind`. `None` disables that one local ceiling.

> [!WARNING]
> **Executable documentation:** The following Python block is executed by the
> documentation test suite with the test process's current privileges.

```python
from obst.core import CoreResource, LimitProfile, ResourcePolicy

profile = LimitProfile(
    "local-large",
    "Local policy for larger containers.",
    (
        (CoreResource.CONTAINER_BYTES, 32 * 1024**3),  # raise one ceiling
        (CoreResource.CHUNKS, None),  # disable only the chunk-count ceiling
    ),
)
policy = ResourcePolicy(profile=profile)

assert policy.maximum(CoreResource.CONTAINER_BYTES) == 32 * 1024**3
assert policy.maximum(CoreResource.CHUNKS) is None
assert policy.maximum(CoreResource.STREAMS) == 65_536  # inherited default
```

Pass the same policy through the complete operation:

```python
reader = ContainerReader(source, policy=policy)
decoder = ChunkDecoder(reader.index, registry, policy=policy)
```

The generic CLI does this for Inspect and every contributed command. A
Packager owns its request contract, but cooperating readers, writers, chunk
operations and adapters must receive the host-selected policy rather than
inventing local defaults halfway through the flow.

`DEFAULT_RESOURCE_POLICY` resolves the immutable `default` profile over Core
resources. The CLI can create and select local profiles with
[`obst limits`](../cli.md#resource-limit-profiles).

## Core resources and defaults

| Resource ID                 | Measures                                 |   Default |
| --------------------------- | ---------------------------------------- | --------: |
| `manifest_bytes`            | Bytes in one encoded manifest            |    16 MiB |
| `encoded_chunk_bytes`       | Encoded bytes in one chunk               |    64 MiB |
| `logical_chunk_bytes`       | Logical bytes in one chunk               |    64 MiB |
| `intermediate_bytes`        | Bytes in one pipeline intermediate       |    64 MiB |
| `materialized_stream_bytes` | Bytes in one materialized stream         |    64 MiB |
| `extensions`                | Extension declarations in one manifest   |     4,096 |
| `recipes`                   | Recipes in one manifest                  |     4,096 |
| `streams`                   | Streams in one manifest                  |    65,536 |
| `total_stages`              | Stages across all recipes                |    65,536 |
| `stages_per_recipe`         | Stages in one recipe                     |        64 |
| `container_bytes`           | Bytes in one complete container          |    16 GiB |
| `chunks`                    | Chunks in one container                  |   262,144 |
| `logical_bytes`             | Logical bytes processed by one operation |    16 GiB |
| `stage_executions`          | Stage executions in one operation        | 1,048,576 |

Every finite maximum is an exact, non-negative `int`. Booleans are rejected.
Wire field widths, framing rules and model validity remain unconditional even
if every relevant local ceiling is `None`.

`container_bytes` counts the committed OBST representation. After the terminal
commit, a reader may request one extra byte only to distinguish clean endpoint
exhaustion from trailing data. That probe is not part of
`ContainerReader.bytes_consumed` and is not charged to the policy.

## Accounting and refusal

Policy is immutable; accounting is operation-local. Readers and writers count
container bytes and chunks. Recipe and chunk sessions count logical bytes and
Stage executions. `materialize_stream()` additionally enforces
`materialized_stream_bytes` because it constructs one complete `bytes` value;
`iter_decoded_chunks()` remains streaming.

Writers reserve the mandatory 64-byte terminal commit before accepting work.
They therefore reject a prefix that fits by itself but could never become a
complete container. Decoders reject declared output and Stage work before
calling a provider, then check the returned result again.

Crossing a finite ceiling raises `ResourceLimitError`:

```python
try:
    reader = ContainerReader(source, policy=policy)
except ResourceLimitError as error:
    print(str(error.resource), error.scope)
    print(error.maximum, error.observed, error.phase)
```

`error.resource` is a `ResourceKind`, not a free-form string. A refusal says
that local policy rejected an operation; the container may still be
structurally valid. The CLI reports this as `resource_limit` with exit code
`10`. Invalid profile state is a separate `limit_state` failure.

## Plugins and isolation

Plugin resources enter a `ResourceCatalog` only when the host loads that
plugin through the ordinary activation path. Plugin profiles are inert until
the host selects one. Container bytes cannot contribute resources, load a
plugin or select a profile.

Stage providers receive a finite `max_output_size` or `None` and must enforce
it while producing output. The Core checks the exact returned `bytes` value,
but it cannot interrupt a provider that blocks, loops, allocates elsewhere or
performs side effects. Resource policy is not a sandbox.

Filesystem, HTTP and other adapter-specific resources belong to the adapter
that measures them. The first-party file resources are documented with
[`obst-defaults`](../../plugins/defaults/docs/files/extraction.md#resource-policy).
CPU time, wall-clock deadlines and cancellation are not part of this resource
contract.
