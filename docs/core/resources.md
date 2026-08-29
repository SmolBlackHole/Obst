# Resource policy and accounting

Parent: [Core API](README.md)

Resource policy answers one question: how much local work may this operation
perform? Accounting answers the next one: how much work has this operation
already performed?

Neither changes the wire format or makes an invalid container valid.

## Table of contents

- [Resource policy and accounting](#resource-policy-and-accounting)
	- [Table of contents](#table-of-contents)
	- [Public model](#public-model)
	- [Create one operation accountant](#create-one-operation-accountant)
	- [Core resources](#core-resources)
	- [Check, record and refuse](#check-record-and-refuse)
	- [Plugins and provider boundary](#plugins-and-provider-boundary)

## Public model

The generic contracts live in `obst.resources`:

```text
ResourceDefinition  ID, unit, default ceiling, summary, aggregation
ResourceKind        typed resource identity
LimitProfile        named ceiling overrides
ResourceCatalog     resources and inert profiles available to one runtime
ResourcePolicy      one profile resolved over one catalog
validate_resource_identifier  canonical external ID grammar
```

The runtime types live in `obst.core`:

```text
CoreResource        resources measured by the Core
ResourceAccounting one operation's current totals and peaks
ResourceLimitError structured local refusal
```

`CoreResource.CHUNKS` is not the string `"chunks"`. Its canonical external ID
is `str(CoreResource.CHUNKS)`. Plugin resources use the same type and qualify
their IDs with an Extension ID, for example
`obst.file@1/archive_members`.

Every definition declares:

- a `ResourceUnit`, either `COUNT` or `BYTES`; and
- a `ResourceAggregation`, either `TOTAL` or `PEAK`.

`TOTAL` adds observations across the operation. `PEAK` retains the largest
observation. These semantics belong to the definition, so hosts and plugins do
not have to infer them from names.

## Create one operation accountant

A profile contains overrides. Omitted resources retain their defaults, while
`None` disables one ceiling without disabling measurement.

> [!WARNING]
> **Executable documentation:** The following Python block is executed by the
> documentation test suite with the test process's current privileges.

```python
from obst.core import CoreResource, ResourceAccounting
from obst.resources import LimitProfile, ResourcePolicy

profile = LimitProfile(
    "local-large",
    "Local policy for larger containers.",
    (
        (CoreResource.CONTAINER_BYTES, 32 * 1024**3),
        (CoreResource.CHUNKS, None),
    ),
)
policy = ResourcePolicy(tuple(CoreResource), profile)
accounting = ResourceAccounting(policy)

assert accounting.maximum(CoreResource.CONTAINER_BYTES) == 32 * 1024**3
assert accounting.maximum(CoreResource.CHUNKS) is None
assert accounting.maximum(CoreResource.STREAMS) == 65_536
```

Create the accountant at the composition root, then pass the same instance to
every cooperating component:

```python
reader = ContainerReader(source, accounting=accounting)
decoder = ChunkDecoder(reader.index, registry, accounting=accounting)
```

Low-level operations never invent a default accountant. Sharing a policy is
not enough, because a policy has no mutable operation state. The CLI resolves
the selected profile, creates one accountant, and supplies it to Inspect or the
selected contributed command.

For an operation using only Core defaults:

```python
accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
```

The [`obst limits`](../cli.md#resource-limit-profiles) commands manage local
profiles. Plugin profiles remain inert until the host selects one.

## Core resources

| Resource ID                 | Aggregation | Measures                                 |   Default |
| --------------------------- | ----------- | ---------------------------------------- | --------: |
| `manifest_bytes`            | peak        | Bytes in one encoded manifest            |    16 MiB |
| `encoded_chunk_bytes`       | peak        | Encoded bytes in one chunk               |    64 MiB |
| `logical_chunk_bytes`       | peak        | Logical bytes in one chunk               |    64 MiB |
| `intermediate_bytes`        | peak        | Bytes in one pipeline intermediate       |    64 MiB |
| `materialized_stream_bytes` | peak        | Bytes in one materialized stream         |    64 MiB |
| `extensions`                | peak        | Extension declarations in one manifest   |     4,096 |
| `recipes`                   | peak        | Recipes in one manifest                  |     4,096 |
| `streams`                   | peak        | Streams in one manifest                  |    65,536 |
| `total_stages`              | peak        | Stages across all recipes                |    65,536 |
| `stages_per_recipe`         | peak        | Stages in one recipe                     |        64 |
| `container_bytes`           | total       | Bytes in one complete container          |    16 GiB |
| `chunks`                    | total       | Chunks in one container                  |   262,144 |
| `logical_bytes`             | total       | Logical bytes processed by one operation |    16 GiB |
| `stage_executions`          | total       | Stage executions in one operation        | 1,048,576 |

Every finite maximum is an exact non-negative `int`; booleans are rejected.
Wire widths, framing and model validity remain unconditional even when a local
ceiling is `None`.

## Check, record and refuse

`check(resource, observed, ...)` validates one absolute value without changing
state. Use it for preflight. A cumulative preflight supplies
`current(resource) + amount` explicitly.

`record(resource, amount, ...)` applies the resource's declared aggregation,
checks the projected value and commits it. A failed check or record does not
mutate the accountant.

```python
try:
    reader = ContainerReader(source, accounting=accounting)
except ResourceLimitError as error:
    print(str(error.resource), error.scope)
    print(error.maximum, error.observed, error.phase)
```

A refusal means local policy declined the operation. The container may still
be structurally valid. The CLI reports this as `resource_limit` with exit code
`10`; invalid local profile state is a separate `limit_state` failure.

Readers and writers record container bytes and chunks. Recipe execution records
logical bytes and Stage executions. `materialize_stream()` also records the
largest materialized stream, while `iter_decoded_chunks()` remains streaming.
Writers reserve enough capacity for the mandatory terminal commit before they
publish an otherwise incomplete prefix.

## Plugins and provider boundary

Plugin resources enter the catalog only when the host loads that plugin through
the normal activation path. Container bytes cannot contribute resources, load
plugins or select profiles.

Plugins receive the same `ResourceAccounting` instance for work they own. Stage
providers are narrower: they receive only `max_output_size` and must enforce it
while producing output. They do not receive the accountant or its complete
policy. Resource limits are therefore not a sandbox and cannot interrupt a
provider that blocks, loops or performs unrelated side effects.

Adapter-specific resources belong to the adapter that records them. The
first-party file resources are documented by
[`obst-defaults`](../../plugins/defaults/docs/files/extraction.md#resource-accounting).
Timeouts and cancellation are deliberately outside this contract for now.
