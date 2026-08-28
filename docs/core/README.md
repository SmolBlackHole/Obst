# OBST core API

Parent: [Documentation index](../README.md)

`obst.core` is the transport-neutral Python API for reading, writing,
inspecting, packaging and decoding OBST byte streams.

It owns container structure and reversible execution. It does not own paths,
filenames, database rows, object-store keys or application values.

## Table of contents

- [OBST core API](#obst-core-api)
	- [Table of contents](#table-of-contents)
	- [Write and recover bytes in memory](#write-and-recover-bytes-in-memory)
	- [Choose a guide](#choose-a-guide)
	- [Public boundary](#public-boundary)

## Write and recover bytes in memory

This complete example uses only the public runtime contracts, one local
identity Stage and 2 in-memory binary endpoints:

> [!WARNING]
> **Executable documentation:** The following Python block runs during tests
> with the current process privileges. It is not sandboxed.

```python
from io import BytesIO
from typing import Self

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ContainerWriter,
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistry,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
    encode_chunk_once,
    materialize_stream,
    require_no_parameters,
    require_stage_output_size,
)


class IdentityExtension:
    extension_id = "org.example/identity@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Identity",
        summary="Return one chunk unchanged.",
        specification_url="https://example.org/obst/identity-v1",
    )

    def bind_encoder(self, parameters: bytes, /) -> Self:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> Self:
        require_no_parameters(self.extension_id, parameters)
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        require_stage_output_size(
            self.extension_id,
            len(data),
            max_output_size=max_output_size,
            operation="encode",
        )
        return data

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        require_stage_output_size(
            self.extension_id,
            len(data),
            max_output_size=max_output_size,
            operation="decode",
        )
        return data

payload = b"OBST is bytes before it becomes fruit."
identity = IdentityExtension()
registry = ExtensionRegistry((identity,))
manifest = Manifest(
    recipes=(Recipe(0, (StageSpec(identity.extension_id),)),),
    streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
)

target = BytesIO()
writer = ContainerWriter(target, manifest)
writer.write_chunk(
    encode_chunk_once(
        payload,
        stream_id=0,
        sequence=0,
        recipe=manifest.recipe(0),
        registry=registry,
    )
)
writer.finish()

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
