# Extending OBST

Parent: [Documentation index](../README.md)

OBST has one core stream contract: [`obst.bytes@1`](../contracts/streams/bytes.md).
Capabilities that give logical bytes additional meaning, transform their
representation, select packaging policy or connect a host endpoint are
extensions. First-party and third-party implementations use the same public
boundaries.

| Boundary       | Owns                                             | Wire-visible ID | Guide                       |
| -------------- | ------------------------------------------------ | --------------- | --------------------------- |
| Stage          | Reversible processing of chunk bytes             | Yes             | [Stages](stages.md)         |
| Codec          | Compression-oriented stage role                  | Yes, as a stage | [Codecs](codecs.md)         |
| Transform      | Structure-oriented stage role                    | Yes, as a stage | [Transforms](transforms.md) |
| Stream profile | Meaning and metadata of logical bytes            | Yes             | [Profiles](profiles.md)     |
| Carrier        | Reading, writing or publishing container bytes   | No              | [Carriers](carriers.md)     |
| Packager       | Policy for producing one valid container         | No              | [Packagers](packagers.md)   |
| Archiver       | Composition between domain inputs and containers | No              | [Archivers](archivers.md)   |
| Plugin command | Host-facing composition supplied by a plugin     | No              | [Plugins](plugins.md)       |
| Plugin         | Named contributions from one distribution        | No new ID kind  | [Plugins](plugins.md)       |

Codecs and transforms are roles implemented through the same Stage Extension
API. Stages, stream profiles, carriers and packagers all enter the same
`ExtensionRegistry`. Only stages and stream types are wire-visible; carrier
and packager IDs remain host-selected runtime identities. Archivers compose
those capabilities for an application workflow and are not registry entries.
Plugin commands enter the generic command host rather than the registry.
Native format tooling such as `inspect` is owned by the host itself and is not
an Extension or plugin contribution.
In Python, `Extension.kind` uses the closed `ExtensionKind` enum. Extension
objects assign `ExtensionKind.STAGE`, `ExtensionKind.STREAM_PROFILE`,
`ExtensionKind.CARRIER` or `ExtensionKind.PACKAGER`; free-form kind strings are
not part of the public contract.

The import boundary mirrors that distinction:

```text
obst                    runtime package metadata
obst.core               neutral runtime contracts and operations
obst.cli                generic command host, native inspection and rendering
provider_distribution.* installable provider implementations
```

> [!IMPORTANT]
> **Explicit composition:** Importing the runtime does not activate extensions,
> mutate a process-wide registry, discover packages or download providers.
> Installing a plugin does not activate it either. The host imports objects
> directly or explicitly activates and loads exactly the plugins it trusts.

Applications may use the public [plugin manager](plugins.md) to inspect
installed `obst.extensions`, `obst.commands` and `obst.conformance` metadata,
persist an enabled set and build an operation-local runtime. Discovery and
activation are inert; only explicit runtime loading imports code, and returned
Extension objects still enter this same registry path.

Every plugin that publishes `obst.extensions` also publishes a matching static
`obst.conformance` suite. Command-only plugins do not need one. This makes the
portable evidence travel with the provider distribution instead of giving
first-party contracts a separate test path.

The names describe different layers:

```text
Python distribution
    -> named plugin entry point
        -> factory returning one or more Extension values
            -> registry capabilities used by Recipes or stream tooling
```

Containers name only versioned Stage and stream-profile contracts. They never
name runtime-only carriers or packagers, Python distributions or plugin entry
points.

## Compose trusted extensions

An extension package exports a self-describing object. That object owns its
canonical ID, descriptor metadata and every executable or interpretive
capability it provides:

```python
from collections.abc import Iterable

from obst.core import Extension, ExtensionRegistry


def compose_runtime(extensions: Iterable[Extension]) -> ExtensionRegistry:
    return ExtensionRegistry(extensions)
```

There is no assembly wrapper, registration decorator or first-party shortcut.
The object itself implements the structural protocols for the capabilities it
offers. `ExtensionDescriptor` contains local descriptive metadata and does not
repeat the ID. The registry is immutable once composed, and one provider per
capability and Extension ID is the limit. The
[registry guide](../core/registry.md) owns conflict rules, snapshots, lookups
and the host trust boundary.

Registration inspects provider shape without executing providers or optional
interpreters. [Recipe execution](../core/recipes.md) owns Stage binding;
[inspection](../core/inspection.md) owns its explicit interpretation policy.

The [contract index](../contracts/README.md) owns the built-in stream contract
and routes to contracts published by provider distributions. These pages
document the Python implementation boundary. The
[recipe execution guide](../core/recipes.md) shows how a registry participates
in encoding and decoding.

The separately installed
[`obst-defaults` documentation](../../plugins/defaults/docs/README.md) is one
concrete provider book. Its first-party ownership grants no special registry or
plugin-loading path.
