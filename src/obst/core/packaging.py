"""Core contracts and values shared by container packaging policies."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from obst.core.errors import PackagingError, SourceConsumedError
from obst.core.io import BinaryWriter
from obst.core.model import (
    Manifest,
    StageSpec,
    Stream,
    validate_extension_id,
)
from obst.core.wire import uint16, uint32


@dataclass(frozen=True, slots=True)
class RecipeSpec:
    """A reusable, possibly empty Stage chain before wire ID assignment."""

    stages: tuple[StageSpec, ...]

    def __post_init__(self) -> None:
        _validate_recipe_stages(self.stages)
        if len(self.stages) > uint16.maximum:
            raise ValueError("a recipe spec cannot contain more than 65535 stages")


@dataclass(frozen=True, slots=True)
class LogicalStreamDescriptor:
    """Logical stream meaning and its fixed default recipe."""

    stream_type: str
    metadata: bytes
    default_recipe: RecipeSpec

    def __post_init__(self) -> None:
        validate_extension_id(self.stream_type)
        _require_bytes("logical stream metadata", self.metadata)
        uint32.require("logical stream metadata", len(self.metadata))


class LogicalStreamSource:
    """One declared stream backed by a single-consumption chunk iterator."""

    __slots__ = ("_chunks", "_consumed", "descriptor", "max_chunk_bytes")

    def __init__(
        self,
        descriptor: LogicalStreamDescriptor,
        chunks: Iterable[bytes],
        *,
        max_chunk_bytes: int,
    ) -> None:
        self.descriptor = descriptor
        self.max_chunk_bytes = _require_nonnegative_int(
            "max_chunk_bytes",
            max_chunk_bytes,
        )
        self._chunks = chunks
        self._consumed = False

    @classmethod
    def from_bytes(
        cls,
        descriptor: LogicalStreamDescriptor,
        data: bytes,
        *,
        chunk_size: int,
    ) -> LogicalStreamSource:
        """Create a bounded source over one already materialized byte string."""
        data = _require_bytes("logical stream data", data)
        chunk_size = _require_positive_int("chunk_size", chunk_size)
        return cls(
            descriptor,
            (
                data[offset : offset + chunk_size]
                for offset in range(0, len(data), chunk_size)
            ),
            max_chunk_bytes=min(chunk_size, len(data)),
        )

    def iter_chunks(self) -> Iterator[bytes]:
        """Claim and return this source's logical chunks exactly once."""
        if self._consumed:
            raise SourceConsumedError()
        self._consumed = True
        return self._validated_chunks()

    def _validated_chunks(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            candidate = cast(object, chunk)
            if type(candidate) is not bytes:
                raise PackagingError(
                    "logical stream source yielded a value that is not exact bytes"
                )
            if len(candidate) > self.max_chunk_bytes:
                raise PackagingError(
                    "logical stream source exceeded its declared maximum chunk size"
                )
            yield candidate


@dataclass(frozen=True, slots=True)
class PackagedStream:
    """Final declaration and accounting for one packaged logical stream."""

    declaration: Stream
    chunk_count: int
    logical_size: int


@dataclass(frozen=True, slots=True)
class PackageResult:
    """Carrier-neutral result of one completed packaging operation."""

    manifest: Manifest
    encoded_size: int
    chunk_count: int
    streams: tuple[PackagedStream, ...]


@runtime_checkable
class PackageWriteOperation(Protocol):
    """Write one already prepared package to a caller-owned binary endpoint."""

    def write_to(self, target: BinaryWriter, /) -> PackageResult:
        """Consume the prepared operation and write one complete container."""
        ...


def _validate_recipe_stages(value: object) -> None:
    if not isinstance(value, tuple):
        raise TypeError("recipe spec stages must be a tuple")
    stages = cast(tuple[object, ...], value)
    if not all(isinstance(stage, StageSpec) for stage in stages):
        raise TypeError("recipe spec stages must contain StageSpec values")


def _require_bytes(name: str, value: object) -> bytes:
    if type(value) is not bytes:
        raise TypeError(f"{name} must be exact bytes")
    return value


def _require_positive_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _require_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value
