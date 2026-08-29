"""Core conversion between logical bytes and wire-ready chunks."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from obst.core.container import ContainerReader
from obst.core.errors import CorruptContainerError
from obst.core.manifest import ManifestIndex
from obst.core.model import Chunk, Recipe, logical_hash
from obst.core.pipeline import RecipeDecoder, RecipeEncoder
from obst.core.registry import ExtensionRegistry
from obst.core.resource_accounting import (
    CoreResource,
    ResourceAccounting,
)


class ChunkEncoder:
    """Encode chunks within one operation-scoped recipe execution session."""

    __slots__ = ("_recipes", "accounting")

    def __init__(
        self,
        registry: ExtensionRegistry,
        *,
        accounting: ResourceAccounting,
    ) -> None:
        if type(accounting) is not ResourceAccounting:
            raise TypeError("chunk encoder accounting must be ResourceAccounting")
        self.accounting = accounting
        self._recipes = RecipeEncoder(registry, accounting=self.accounting)

    def preflight(self, recipes: Iterable[Recipe], /) -> None:
        """Resolve and bind every supplied recipe before encoding chunks."""
        self._recipes.preflight(recipes)

    def encode(
        self,
        data: bytes,
        *,
        stream_id: int,
        sequence: int,
        recipe: Recipe,
    ) -> Chunk:
        """Encode one exact logical byte chunk and attach its identity data."""
        if type(data) is not bytes:
            raise TypeError("logical chunk data must be exact bytes")
        scope = f"stream {stream_id} chunk {sequence}"
        self.accounting.record(
            CoreResource.LOGICAL_CHUNK_BYTES,
            len(data),
            scope=scope,
            phase="chunk_encode",
        )
        encoded_payload = self._recipes.encode(
            data,
            recipe,
            max_output_size=self.accounting.maximum(CoreResource.ENCODED_CHUNK_BYTES),
        )
        self.accounting.record(
            CoreResource.ENCODED_CHUNK_BYTES,
            len(encoded_payload),
            scope=scope,
            phase="chunk_encode",
        )
        return Chunk(
            stream_id=stream_id,
            sequence=sequence,
            recipe_id=recipe.recipe_id,
            logical_size=len(data),
            logical_hash=logical_hash(data),
            encoded_payload=encoded_payload,
        )


class ChunkDecoder:
    """Decode validated chunks against one immutable manifest lookup."""

    __slots__ = ("_index", "_recipes", "accounting")

    def __init__(
        self,
        index: ManifestIndex,
        registry: ExtensionRegistry,
        *,
        accounting: ResourceAccounting,
    ) -> None:
        if type(index) is not ManifestIndex:
            raise TypeError("chunk decoder requires an exact ManifestIndex")
        if type(accounting) is not ResourceAccounting:
            raise TypeError("chunk decoder accounting must be ResourceAccounting")
        self._index = index
        self.accounting = accounting
        self._recipes = RecipeDecoder(registry, accounting=self.accounting)

    def decode(self, chunk: Chunk, /) -> bytes:
        """Decode one chunk and verify its exact logical size and content hash."""
        self._index.stream(chunk.stream_id)
        recipe = self._index.recipe(chunk.recipe_id)
        return _decode_with_recipe(
            chunk,
            recipe,
            self._recipes,
            accounting=self.accounting,
        )


def encode_chunk_once(
    data: bytes,
    *,
    stream_id: int,
    sequence: int,
    recipe: Recipe,
    registry: ExtensionRegistry,
    accounting: ResourceAccounting,
) -> Chunk:
    """Encode one chunk as a complete bounded operation."""
    return ChunkEncoder(registry, accounting=accounting).encode(
        data,
        stream_id=stream_id,
        sequence=sequence,
        recipe=recipe,
    )


def decode_chunk_once(
    chunk: Chunk,
    recipe: Recipe,
    registry: ExtensionRegistry,
    *,
    accounting: ResourceAccounting,
) -> bytes:
    """Decode one chunk as a complete bounded operation."""
    if recipe.recipe_id != chunk.recipe_id:
        raise ValueError(
            f"chunk selects recipe {chunk.recipe_id}, got recipe {recipe.recipe_id}"
        )
    return _decode_with_recipe(
        chunk,
        recipe,
        RecipeDecoder(registry, accounting=accounting),
        accounting=accounting,
    )


def iter_decoded_chunks(
    reader: ContainerReader,
    registry: ExtensionRegistry,
) -> Iterator[tuple[Chunk, bytes]]:
    """Consume a reader and yield logical chunk bytes in physical order."""
    decoder = ChunkDecoder(
        reader.index,
        registry,
        accounting=reader.accounting,
    )
    for chunk in reader.iter_chunks():
        yield chunk, decoder.decode(chunk)


def materialize_stream(
    reader: ContainerReader,
    stream_id: int,
    registry: ExtensionRegistry,
) -> bytes:
    """Consume a reader and materialize one bounded logical stream."""
    reader.index.stream(stream_id)
    decoder = ChunkDecoder(
        reader.index,
        registry,
        accounting=reader.accounting,
    )
    output = bytearray()
    for chunk in reader.iter_chunks():
        if chunk.stream_id != stream_id:
            continue
        reader.accounting.record(
            CoreResource.MATERIALIZED_STREAM_BYTES,
            len(output) + chunk.logical_size,
            scope=f"stream {stream_id}",
            phase="stream_materialize",
        )
        output.extend(decoder.decode(chunk))
    return bytes(output)


def _decode_with_recipe(
    chunk: Chunk,
    recipe: Recipe,
    decoder: RecipeDecoder,
    *,
    accounting: ResourceAccounting,
) -> bytes:
    scope = f"stream {chunk.stream_id} chunk {chunk.sequence}"
    accounting.record(
        CoreResource.ENCODED_CHUNK_BYTES,
        chunk.encoded_size,
        scope=scope,
        phase="chunk_decode",
    )
    accounting.record(
        CoreResource.LOGICAL_CHUNK_BYTES,
        chunk.logical_size,
        scope=scope,
        phase="chunk_decode",
    )
    decoded = decoder.decode(
        chunk.encoded_payload,
        recipe,
        expected_size=chunk.logical_size,
    )
    if logical_hash(decoded) != chunk.logical_hash:
        raise CorruptContainerError("decoded chunk hash mismatch")
    return decoded
