# OBST core API

Parent: [Documentation index](../README.md)

`obst.core` is the transport-neutral Python API for reading, writing,
inspecting, packaging and decoding OBST byte streams.

It owns container structure and reversible execution. It does not own paths,
filenames, database rows, object-store keys or application values.

## Table of contents

- [OBST core API](#obst-core-api)
	- [Table of contents](#table-of-contents)
	- [Package and recover bytes in memory](#package-and-recover-bytes-in-memory)
	- [Choose a guide](#choose-a-guide)
	- [Public boundary](#public-boundary)

## Package and recover bytes in memory

This complete example uses the public core contracts, explicitly selected RAW
and fixed-packager extensions, and 2 in-memory binary endpoints:

> [!WARNING]
> **Executable documentation:** The following Python block runs during tests
> with the current process privileges. It is not sandboxed.

```python
from io import BytesIO

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ExtensionRegistry,
    LogicalStreamDescriptor,
    LogicalStreamSource,
    RecipeSpec,
    StageSpec,
    materialize_stream,
)
from obst_defaults.codecs import RawExtension
from obst_defaults.packagers import FixedPackageRequest, FixedPackagerExtension

payload = b"OBST is bytes before it becomes fruit."
raw = RawExtension()
fixed = FixedPackagerExtension()
registry = ExtensionRegistry((raw, fixed))
recipe = RecipeSpec((StageSpec(raw.extension_id, b""),))
source = LogicalStreamSource.from_bytes(
    LogicalStreamDescriptor(
        stream_type=BYTES_STREAM_TYPE,
        metadata=b"",
        default_recipe=recipe,
    ),
    payload,
    chunk_size=64 * 1024,
)

target = BytesIO()
operation = registry.require_packager_provider(fixed.extension_id).prepare_package(
    FixedPackageRequest(registry=registry, sources=(source,))
)
operation.write_to(target)

reader = ContainerReader(BytesIO(target.getvalue()))
assert materialize_stream(reader, stream_id=0, registry=registry) == payload
```

The same core operations accept any compatible binary reader or writer. Files,
object stores and transactional publication remain adapter concerns.

## Choose a guide

| Task                                          | Guide                                |
| --------------------------------------------- | ------------------------------------ |
| Compose trusted extension capabilities        | [Extension registry](registry.md)    |
| Parse validated encoded chunks                | [Reading](reading.md)                |
| Write a known manifest and encoded chunks     | [Writing](writing.md)                |
| Execute recipes and individual chunks         | [Recipes and chunks](recipes.md)     |
| Inspect structure without decoding            | [Inspection](inspection.md)          |
| Turn logical chunk sources into one container | [Packaging](packaging.md)            |
| Configure bounded local work                  | [Resource limits](resources.md)      |
| Understand Python's scalar and record layouts | [Wire mapping](wire.md)              |
| Handle runtime failures                       | [Error reference](../errors.md)      |
| Understand the exact bytes                    | [Format specification](../format.md) |
| Understand the architecture                   | [Design notes](../design.md)         |

## Public boundary

`obst.core` is the supported public import boundary. Common entry points include:

```python
from obst.core import (
    ChunkDecoder,
    ChunkEncoder,
    ContainerReader,
    ContainerSummary,
    ContainerWriter,
    ExtensionRegistry,
    ManifestIndex,
    RecipeDecoder,
    RecipeEncoder,
    ResourceLimits,
)
```

The root `obst` package exposes `FormatVersion` and the reference
implementation's `format_version` value. Concrete first-party codecs,
profiles, carriers, packagers and file adapters are supplied by the separate
`obst-defaults` distribution and imported from `obst_defaults`. Third-party
packages implement the same public core contracts.
