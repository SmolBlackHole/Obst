# Recipe and chunk execution

Parent: [Core API](README.md)

Recipe execution applies registered stage contracts to one byte string. Chunk
execution adds the identity and integrity data needed to prove the same logical
bytes return after decoding. This page owns the direct Python API between the
[packager](packaging.md) and [stage providers](../extensions/stages.md#provider-protocols).
The [extension registry](registry.md) owns capability composition, and the
[container vocabulary](../anatomy.md#the-pieces-at-a-glance) defines the stored
pieces.

## Table of contents

- [Recipe and chunk execution](#recipe-and-chunk-execution)
	- [Table of contents](#table-of-contents)
	- [Execute one recipe](#execute-one-recipe)
	- [Reuse recipe bindings](#reuse-recipe-bindings)
	- [Execute one chunk](#execute-one-chunk)
	- [Validate manifest resources](#validate-manifest-resources)
	- [Operation budgets](#operation-budgets)

## Execute one recipe

A `Recipe` stores the ordered stage specifications used by one or more chunks.
Encoding follows declaration order. Decoding walks the same recipe backward:

> [!WARNING]
> **Executable documentation:** The following Python block runs during tests
> with the current process privileges. It is not sandboxed.

```python
from typing import Self

from obst.core import (
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistry,
    Recipe,
    ResourceLimits,
    StageSpec,
    decode_recipe,
    encode_recipe,
    require_no_parameters,
    require_stage_output_size,
)


class ReverseExtension:
    extension_id = "org.example/reverse@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Reverse",
        summary="Reverse the bytes in one chunk.",
        specification_url="https://example.org/obst/reverse-v1",
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
        return data[::-1]

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return self.encode(data, max_output_size=max_output_size)


reverse = ReverseExtension()
registry = ExtensionRegistry((reverse,))
recipe = Recipe(
    0,
    (StageSpec(reverse.extension_id),),
)
limits = ResourceLimits(max_intermediate_bytes=1024 * 1024)
logical = b"banana" * 100

encoded = encode_recipe(logical, recipe, registry, limits=limits)
assert encoded == logical[::-1]
recovered = decode_recipe(
    encoded,
    recipe,
    registry,
    expected_size=len(logical),
    limits=limits,
)

assert recovered == logical
```

`decode_recipe()` verifies the expected output size. It cannot verify the
logical hash because a recipe has no chunk identity. Use the chunk helpers
when recovered-byte integrity matters.

## Reuse recipe bindings

Standalone helpers create one bounded operation. `RecipeEncoder` and
`RecipeDecoder` instead cache immutable directional bindings across many chunks
while keeping cumulative logical-byte and stage-execution accounting inside the
session:

```python
from obst.core import RecipeDecoder, RecipeEncoder

encoder = RecipeEncoder(registry, limits=limits)
encoder.preflight((recipe,))
encoded_a = encoder.encode(logical_a, recipe)
encoded_b = encoder.encode(logical_b, recipe)

decoder = RecipeDecoder(registry, limits=limits)
recovered_a = decoder.decode(
    encoded_a,
    recipe,
    expected_size=len(logical_a),
)
```

Encoder preflight resolves every stage provider for every supplied recipe
before invoking the first bind callback. Decoders bind only recipes they
actually execute. Binding validates exact opaque parameter bytes once per
recipe, direction and session.

## Execute one chunk

`encode_chunk_once()` produces a model value ready for `ContainerWriter`. It
records the stream ID, sequence, recipe ID, logical size, logical hash and
encoded payload. `decode_chunk_once()` verifies both the declared size and
logical hash:

```python
from obst.core import decode_chunk_once, encode_chunk_once

chunk = encode_chunk_once(
    logical,
    stream_id=0,
    sequence=0,
    recipe=recipe,
    registry=registry,
    limits=limits,
)
recovered = decode_chunk_once(chunk, recipe, registry, limits=limits)

assert recovered == logical
```

For multiple chunks, use the symmetrical sessions instead of repeatedly
constructing standalone operations:

```python
from obst.core import ChunkDecoder, ChunkEncoder, ManifestIndex

chunk_encoder = ChunkEncoder(registry, limits=limits)
chunk_encoder.preflight((recipe,))
chunk = chunk_encoder.encode(
    logical,
    stream_id=0,
    sequence=0,
    recipe=recipe,
)

index = ManifestIndex(manifest)
chunk_decoder = ChunkDecoder(index, registry, limits=limits)
recovered = chunk_decoder.decode(chunk)
```

`ManifestIndex` is an immutable runtime lookup for declared streams, recipes
and extensions. It is not serialized and is not a byte-offset index.

The helpers do not serialize container framing or encoded CRCs. That is the
writer's job. The [writing guide](writing.md) owns framing, and the
[format specification](../format.md) defines the resulting bytes.

## Validate manifest resources

Call `validate_manifest_resources()` to prove that a manifest fits local
resource policy without constructing its encoded body:

```python
from obst.core import validate_manifest_resources

validate_manifest_resources(manifest, limits=limits)
```

This check does not resolve stage providers or invoke extension code.
`RecipeEncoder.preflight()` and `ChunkEncoder.preflight()` resolve and bind the
selected encoders. The shipped `obst.fixed@1` packager composes both checks
before it writes chunks; `ContainerWriter` also validates and encodes its final
manifest during construction.

Every provider required by one recipe is resolved from the immutable
[registry](registry.md#resolve-capabilities) before that recipe invokes its
first provider callback. A missing later stage therefore fails without
partially executing the recipe.

## Operation budgets

Each standalone recipe or chunk call owns one independent `ResourceLimits`
budget. `RecipeEncoder`, `RecipeDecoder`, `ChunkEncoder` and `ChunkDecoder`
retain their own cumulative logical and stage-execution counters across calls.
Readers and writers own separate structural counters; sharing `ResourceLimits`
shares policy, not mutable accounting.

Use the [`obst.fixed@1` packager provider](../extensions/packagers/fixed.md) for
fixed multi-stream packaging. Use
[`ChunkDecoder`](reading.md#selective-chunk-decoding) when an adapter needs
selective decoding without access to private core state.

The [resource guide](resources.md) defines counters and defaults. The
[packaging guide](packaging.md) and [reading guide](reading.md) document the 2
composition roots.
