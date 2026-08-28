# Recipe and chunk execution

Parent: [Core API](README.md)

This page owns the Python operations that apply an already registered
[Recipe](../anatomy.md#recipes-describe-reversible-representation) or turn its
result into a [Chunk](../anatomy.md#chunks-make-the-stream-bounded). The
[Stage guide](../extensions/stages.md#provider-protocols) owns provider
implementation, and [writing](writing.md) owns container framing.

## Table of contents

- [Recipe and chunk execution](#recipe-and-chunk-execution)
	- [Table of contents](#table-of-contents)
	- [Execute one Recipe](#execute-one-recipe)
	- [Reuse Recipe bindings](#reuse-recipe-bindings)
	- [Execute one Chunk](#execute-one-chunk)
	- [Validate manifest resources](#validate-manifest-resources)
	- [Operation budgets](#operation-budgets)

## Execute one Recipe

`encode_recipe()` applies Stage encoders in declaration order.
`decode_recipe()` applies their decoders in reverse order and requires the
expected logical size:

```python
from obst.core import (
    ExtensionRegistry,
    Recipe,
    ResourceLimits,
    decode_recipe,
    encode_recipe,
)


def round_trip_recipe(
    logical: bytes,
    recipe: Recipe,
    registry: ExtensionRegistry,
    limits: ResourceLimits,
) -> bytes:
    encoded = encode_recipe(logical, recipe, registry, limits=limits)
    return decode_recipe(
        encoded,
        recipe,
        registry,
        expected_size=len(logical),
        limits=limits,
    )
```

The size check catches expansion or truncation after decoding. A Recipe has no
stream or Chunk identity, so this operation cannot verify a logical hash. Use
the Chunk API when recovered-byte integrity matters.

## Reuse Recipe bindings

The standalone helpers create one bounded operation per call. Long-running
operations use `RecipeEncoder` and `RecipeDecoder` instead:

```python
from obst.core import RecipeDecoder, RecipeEncoder

encoder = RecipeEncoder(registry, limits=limits)
encoder.preflight(recipes)
encoded_a = encoder.encode(logical_a, recipe_a)
encoded_b = encoder.encode(logical_b, recipe_b)

decoder = RecipeDecoder(registry, limits=limits)
recovered_a = decoder.decode(
    encoded_a,
    recipe_a,
    expected_size=len(logical_a),
)
```

`RecipeEncoder.preflight()` resolves every Stage provider for all supplied
Recipes before invoking the first bind callback. It then caches each immutable
directional binding. `RecipeDecoder` binds lazily because a reader need not
decode every Recipe declared by a container.

Both sessions validate the exact opaque parameter bytes once per Recipe,
direction and session. Their cumulative logical-byte and Stage-execution
counters remain active across calls.

## Execute one Chunk

`encode_chunk_once()` adds stream identity, sequence, Recipe identity, logical
size and logical hash to the encoded payload. `decode_chunk_once()` checks the
Recipe ID, recovers the bytes and verifies their declared size and hash:

```python
from obst.core import (
    ExtensionRegistry,
    Recipe,
    ResourceLimits,
    decode_chunk_once,
    encode_chunk_once,
)


def round_trip_chunk(
    logical: bytes,
    recipe: Recipe,
    registry: ExtensionRegistry,
    limits: ResourceLimits,
) -> bytes:
    chunk = encode_chunk_once(
        logical,
        stream_id=0,
        sequence=0,
        recipe=recipe,
        registry=registry,
        limits=limits,
    )
    return decode_chunk_once(chunk, recipe, registry, limits=limits)
```

Use the session types when processing several Chunks:

| Operation | Session        | Additional responsibility                                      |
| --------- | -------------- | -------------------------------------------------------------- |
| Encode    | `ChunkEncoder` | Reuses Recipe bindings and constructs complete `Chunk` values. |
| Decode    | `ChunkDecoder` | Resolves each Chunk through one immutable `ManifestIndex`.     |

`ManifestIndex` is a lookup for declared streams, Recipes and Extensions. It
is not serialized and does not contain byte offsets.

Chunk helpers return model values. `ContainerWriter` adds the stored header,
payload CRC and terminal commitment. The [format specification](../format.md)
defines those bytes.

## Validate manifest resources

`validate_manifest_resources()` checks a manifest against local policy without
constructing its encoded body:

```python
from obst.core import validate_manifest_resources

validate_manifest_resources(manifest, limits=limits)
```

The check invokes no Extension code. Encoder preflight separately resolves and
binds every selected provider before a Packager publishes container bytes.
`ContainerWriter` also validates and encodes its final manifest during
construction.

Every provider required by one Recipe is resolved from the immutable
[registry](registry.md#resolve-capabilities) before that Recipe invokes its
first bind callback. A missing later Stage therefore cannot leave a Recipe
partially executed.

## Operation budgets

Each standalone Recipe or Chunk helper owns an independent budget under the
supplied `ResourceLimits`. Session objects retain cumulative logical-byte and
Stage-execution counters across calls. Readers and writers own separate
structural counters; sharing `ResourceLimits` shares policy, not mutable
accounting.

The [resource guide](resources.md) owns limits and accounting. The
[packaging guide](packaging.md) composes forward execution across logical
sources, while [reading](reading.md#selective-chunk-decoding) composes selective
recovery through `ChunkDecoder`.
