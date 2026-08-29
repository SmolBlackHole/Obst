# Fixed packager: `obst.fixed@1`

Parent: [obst-defaults Packagers](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

The fixed packager writes every logical source exactly once using the recipe
already declared by that source. It performs no candidate search and no hidden
codec selection. The resulting manifest and ID assignment are deterministic
for the same ordered declarations and provider outputs.

## Table of contents

- [Fixed packager: `obst.fixed@1`](#fixed-packager-obstfixed1)
	- [Table of contents](#table-of-contents)
	- [Capability](#capability)
	- [Prepare an operation](#prepare-an-operation)
	- [Manifest construction](#manifest-construction)
	- [Execution and limits](#execution-and-limits)
	- [What fixed does not mean](#what-fixed-does-not-mean)

## Capability

| Property        | Value                                            |
| --------------- | ------------------------------------------------ |
| Extension ID    | `obst.fixed@1`                                   |
| Extension kind  | Packager                                         |
| Provider        | `prepare_package()`                              |
| Request type    | `FixedPackageRequest`                            |
| Python provider | `obst_defaults.packagers.FixedPackagerExtension` |
| Wire-visible    | No                                               |

The ID selects local packaging policy. A container produced by this provider
does not record that `obst.fixed@1` was used.

## Prepare an operation

```python
from obst.core import ExtensionRegistry
from obst_defaults.packagers import FixedPackageRequest, FixedPackagerExtension

fixed = FixedPackagerExtension()
registry = ExtensionRegistry((*stage_and_profile_extensions, fixed))
provider = registry.require_packager_provider(fixed.extension_id)
operation = provider.prepare_package(
    FixedPackageRequest(registry=registry, sources=logical_sources)
)
```

`sources` must be a non-empty tuple of distinct `LogicalStreamSource` objects.
Each source is single-use and carries its own stream descriptor, default recipe
and maximum logical chunk size.

## Manifest construction

The provider:

1. keeps sources in caller order and assigns stream IDs from 0;
2. deduplicates equal `RecipeSpec` values by first appearance;
3. assigns recipe IDs from 0;
4. collects referenced stream-type and stage IDs;
5. copies registered specification URLs for those wire-visible contracts; and
6. validates the complete manifest before writing the container header.

The same ordered sources and descriptors therefore produce the same manifest.
Equal complete container bytes additionally require deterministic stage
encoders.

## Execution and limits

Before writing, the operation checks source declarations, manifest resources
and every required encoder. It then consumes each source once, encodes each
logical chunk with that stream's recipe and finishes the `ContainerWriter` so a
terminal commit closes the representation.

`FixedPackageRequest.accounting` requires one explicit operation-local
`ResourceAccounting`. The operation passes it unchanged to source preflight,
recipe execution and container writing. It never replaces the host selection
with a local default.
The
[resource guide](../../../../docs/toolchain/resources.md) documents the defaults and refusal
semantics.

## What fixed does not mean

Fixed means the recipe decision is already made. It does not mean one global
recipe, one codec, one chunk size or canonical encoded bytes. Different sources
may declare different recipes, and a stage provider may still have multiple
valid encodings unless its own contract requires canonical output.

Automatic candidate search and two-pass spooling are separate roadmap work.
See the [packager overview](../../../../docs/toolchain/extension-api/packagers.md#third-party-policies) for the policy
boundary and [core packaging](../../../../docs/toolchain/internals/packaging.md) for the shared operation
contracts.
