# Container inspection

Parent: [Core API](README.md)

`inspect_container()` consumes a `ContainerReader` once and returns a renderer-
neutral `ContainerInspection` dataclass. The CLI's human and JSON views are two
presentations of this same result.

Structural inspection does not require a stream profile or Stage provider.
The supplied registry only adds local descriptors, decoder availability and
optional trusted interpreters to the report.

The [container anatomy](../anatomy.md#the-pieces-at-a-glance) defines the
streams, recipes, chunks and stages reported here.

## Table of contents

- [Container inspection](#container-inspection)
	- [Table of contents](#table-of-contents)
	- [Reported structure](#reported-structure)
	- [Resource footprint](#resource-footprint)
	- [Declared and local specification URLs](#declared-and-local-specification-urls)
	- [Optional interpretation](#optional-interpretation)
		- [Interpreter diagnostics and failures](#interpreter-diagnostics-and-failures)

```python
from io import BytesIO

from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ContainerReader,
    ExtensionRegistry,
    ResourceAccounting,
    inspect_container,
)

accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
inspection = inspect_container(
    ContainerReader(BytesIO(container_bytes), accounting=accounting),
    registry=ExtensionRegistry(trusted_extensions),
)
```

The [extension registry](registry.md) is an immutable host-approved capability
set. Passing one reports descriptors and decoder availability but does not
authorize interpreter callbacks.

Inspection validates the complete stored container, including its terminal
commitment, but does not decode payload chunks. `logical_recovery` is therefore
`not_attempted`. Successful inspection leaves its reader `complete`; a failed
structural pass leaves it terminally `failed`.

## Reported structure

The result includes:

- the inspected `FormatVersion`, manifest and shared final `ContainerSummary`;
- per-stream chunk counts, declared logical size, encoded payload size and
  actual recipe usage;
- every recipe, its raw stage parameters, optional interpretation and actual
  chunk count; and
- every stage's declared recipe use, actual chunk use and local decoder
  capability.

Renderers derive the numeric version, codename and combined label from the
inspection result instead of assembling those fields independently.

Container-wide decodability depends only on stages reached transitively from
recipes referenced by actual chunks. An unavailable stage in an unused recipe
remains visible in `missing_declared_stages` but not in
`missing_required_stages`.

## Resource footprint

`ContainerInspection.summary` contains container size, total declared logical
bytes and top-level stream, recipe and chunk counts.

`ContainerInspection.resources` is a `ContainerResourceFootprint` containing
the remaining exact facts derived during the same structural pass:

- manifest size and declaration counts;
- largest encoded and logical chunk;
- stage executions implied by actual Recipe usage; and
- the largest logical stream size relevant to full materialization.

These values describe the representation, not the inspecting machine.
The selected resource policy and operation accounting remain local and are not
loaded from container metadata. Peak memory, execution time and intermediate
Stage sizes cannot be known without executing a particular local
implementation, so they remain absent from structural inspection.

## Declared and local specification URLs

The two URLs have different provenance:

- `declared_specification_url` comes from the inspected manifest. It records
  what the producer declared when packaging the container.
- `local_specification_url` comes from the `ExtensionDescriptor` registered by
  the inspecting process.

First-party output normally shows the same URL twice because the packer copied
the same registered descriptor into the manifest. They may differ, and either
may be absent. The comparison helps tooling expose stale or conflicting
provenance without deciding which website to trust.

`Local` describes the source of the metadata, the local registry, not the URL's
network location. OBST does not derive this value from the declared URL or find
a document on disk. A remote HTTPS URL can therefore be the local registry's
specification URL.

Neither URL is fetched. Neither contributes to extension identity. The
versioned extension ID remains authoritative.

## Optional interpretation

Structural inspection is the core default. It invokes no stream-metadata or
stage-parameter interpreter, including for extensions present in the supplied
registry. A host opts selected IDs into semantic interpretation explicitly:

```python
from obst.core import InspectionInterpretationPolicy

policy = InspectionInterpretationPolicy(
    frozenset(
        {
            "org.example/table@1",
            "org.example/reverse@1",
        }
    )
)
inspection = inspect_container(
    ContainerReader(BytesIO(container_bytes), accounting=accounting),
    registry=ExtensionRegistry(trusted_extensions),
    interpretation_policy=policy,
)
```

The allowlist controls callbacks only. Raw metadata and parameter bytes remain
authoritative, and capability reporting still uses the complete immutable
registry. Unknown extensions do not invalidate structurally valid container
bytes.

An allowed interpreter may return an `InspectionInterpretation` containing
`error`; that diagnostic is retained without changing structural validity. If
an interpreter raises an ordinary `Exception` or returns a value other than an
exact `InspectionInterpretation`, the explicitly interpreted inspection stops
with `ExtensionContractError`. Field names, scalar values, labels and errors
are validated again at this provider boundary. Every ordinary `Exception`,
including an existing `ExtensionContractError`, is wrapped in a new
`ExtensionContractError` whose `__cause__` preserves the original exception.
`BaseException` subclasses outside `Exception` propagate unchanged.

### Interpreter diagnostics and failures

Three outcomes are intentionally different:

| Interpreter situation                                        | Inspection result                                                     |
| ------------------------------------------------------------ | --------------------------------------------------------------------- |
| no interpretation policy                                     | no callback runs; raw bytes and capability facts remain available     |
| callback returns `InspectionInterpretation(error="invalid")` | structural inspection succeeds and retains the extension's diagnostic |
| callback raises or returns the wrong type                    | interpreted inspection fails with `ExtensionContractError`            |

An interpreter-reported `error` means "these opaque bytes have no local
presentation", not "the OBST container is structurally invalid". A raised
exception instead means the host-authorized extension code failed its runtime
contract.

Use callback-free inspection when semantic metadata does not need local
presentation:

```python
inspection = inspect_container(
    ContainerReader(BytesIO(container_bytes), accounting=accounting),
    registry=registry,
)
```

Passing a registry alone never opts its interpreters in. The [extension
registry](registry.md#keep-the-trust-boundary-explicit) owns the trust decision;
the [runtime error reference](../errors.md) owns failure classification.

The command-line presentation and JSON schema are documented in the
[CLI guide](../cli.md).
