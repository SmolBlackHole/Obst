"""Core conversion between logical bytes and wire-ready chunks."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from obst.core.container import ContainerReader
from obst.core.errors import CorruptContainerError, ResourceLimitError
from obst.core.manifest import ManifestIndex
from obst.core.model import Chunk, Recipe, logical_hash
from obst.core.pipeline import RecipeDecoder, RecipeEncoder
from obst.core.registry import ExtensionRegistry
from obst.core.resources import DEFAULT_RESOURCE_LIMITS, ResourceBudget, ResourceLimits


class ChunkEncoder:
    """Encode chunks within one operation-scoped recipe execution session."""

    __slots__ = ("_limits", "_recipes")

    def __init__(
        self,
        registry: ExtensionRegistry,
        *,
        limits: ResourceLimits = DEFAULT_RESOURCE_LIMITS,
    ) -> None:
        self._limits = limits
        self._recipes = RecipeEncoder(registry, limits=limits)

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
        _require_chunk_size(
            resource="logical_chunk_bytes",
            scope=scope,
            maximum=self._limits.max_logical_chunk_bytes,
            observed=len(data),
            phase="chunk_encode",
        )
        encoded_payload = self._recipes.encode(data, recipe)
        _require_chunk_size(
            resource="encoded_chunk_bytes",
            scope=scope,
            maximum=self._limits.max_encoded_chunk_bytes,
            observed=len(encoded_payload),
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

    __slots__ = ("_index", "_limits", "_recipes")

    def __init__(
        self,
        index: ManifestIndex,
        registry: ExtensionRegistry,
        *,
        limits: ResourceLimits = DEFAULT_RESOURCE_LIMITS,
    ) -> None:
        if type(index) is not ManifestIndex:
            raise TypeError("chunk decoder requires an exact ManifestIndex")
        self._index = index
        self._limits = limits
        self._recipes = RecipeDecoder(registry, limits=limits)

    def decode(self, chunk: Chunk, /) -> bytes:
        """Decode one chunk and verify its exact logical size and content hash."""
        self._index.stream(chunk.stream_id)
        recipe = self._index.recipe(chunk.recipe_id)
        return _decode_with_recipe(
            chunk,
            recipe,
            self._recipes,
            limits=self._limits,
        )


def encode_chunk_once(
    data: bytes,
    *,
    stream_id: int,
    sequence: int,
    recipe: Recipe,
    registry: ExtensionRegistry,
    limits: ResourceLimits = DEFAULT_RESOURCE_LIMITS,
) -> Chunk:
    """Encode one chunk as a complete bounded operation."""
    return ChunkEncoder(registry, limits=limits).encode(
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
    limits: ResourceLimits = DEFAULT_RESOURCE_LIMITS,
) -> bytes:
    """Decode one chunk as a complete bounded operation."""
    if recipe.recipe_id != chunk.recipe_id:
        raise ValueError(
            f"chunk selects recipe {chunk.recipe_id}, got recipe {recipe.recipe_id}"
        )
    return _decode_with_recipe(
        chunk,
        recipe,
        RecipeDecoder(registry, limits=limits),
        limits=limits,
    )


def iter_decoded_chunks(
    reader: ContainerReader,
    registry: ExtensionRegistry,
) -> Iterator[tuple[Chunk, bytes]]:
    """Consume a reader and yield logical chunk bytes in physical order."""
    decoder = ChunkDecoder(
        reader.index,
        registry,
        limits=reader.limits,
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
        limits=reader.limits,
    )
    materialization = ResourceBudget(reader.limits)
    output = bytearray()
    for chunk in reader.iter_chunks():
        if chunk.stream_id != stream_id:
            continue
        materialization.require(
            resource="materialized_stream_bytes",
            scope=f"stream {stream_id}",
            maximum=reader.limits.max_materialized_stream_bytes,
            observed=len(output) + chunk.logical_size,
            phase="stream_materialize",
        )
        output.extend(decoder.decode(chunk))
    return bytes(output)


def _decode_with_recipe(
    chunk: Chunk,
    recipe: Recipe,
    decoder: RecipeDecoder,
    *,
    limits: ResourceLimits,
) -> bytes:
    scope = f"stream {chunk.stream_id} chunk {chunk.sequence}"
    _require_chunk_size(
        resource="encoded_chunk_bytes",
        scope=scope,
        maximum=limits.max_encoded_chunk_bytes,
        observed=chunk.encoded_size,
        phase="chunk_decode",
    )
    _require_chunk_size(
        resource="logical_chunk_bytes",
        scope=scope,
        maximum=limits.max_logical_chunk_bytes,
        observed=chunk.logical_size,
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


def _require_chunk_size(
    *,
    resource: str,
    scope: str,
    maximum: int | None,
    observed: int,
    phase: str,
) -> None:
    if maximum is not None and observed > maximum:
        raise ResourceLimitError(
            resource=resource,
            scope=scope,
            maximum=maximum,
            observed=observed,
            phase=phase,
        )
