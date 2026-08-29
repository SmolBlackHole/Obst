# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Core language-neutral concepts represented as Python value objects."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import cast

from obst.core.wire import BLAKE2S_128_SIZE, uint16, uint32, uint64

_EXTENSION_ID = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)?@[1-9][0-9]*$"
)
_ABSOLUTE_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

BYTES_STREAM_TYPE = "obst.bytes@1"


def logical_hash(data: bytes) -> bytes:
    """Return the wire-format hash of one logical chunk payload."""
    return hashlib.blake2s(data, digest_size=BLAKE2S_128_SIZE).digest()


def _require_bytes(name: str, value: object) -> None:
    if type(value) is not bytes:
        raise TypeError(f"{name} must be bytes")


def _require_tuple(name: str, value: object, item_type: type[object]) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    items = cast(tuple[object, ...], value)
    if not all(isinstance(item, item_type) for item in items):
        raise TypeError(f"{name} must contain only {item_type.__name__} values")


def validate_extension_id(extension_id: str) -> None:
    """Validate the canonical ASCII extension identity syntax."""
    if not _EXTENSION_ID.fullmatch(extension_id):
        raise ValueError(f"invalid OBST extension id: {extension_id!r}")


def validate_specification_url(specification_url: object) -> None:
    """Validate one portable absolute specification URL syntax."""
    if not isinstance(specification_url, str):
        raise TypeError("specification_url must be a string")
    if not specification_url or not _ABSOLUTE_URL.match(specification_url):
        raise ValueError("specification_url must be an absolute URL")
    try:
        specification_url.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "specification_url must contain only ASCII characters"
        ) from exc
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in specification_url
    ):
        raise ValueError("specification_url cannot contain whitespace or controls")


def _validate_wire_specification_url(specification_url: object) -> None:
    validate_specification_url(specification_url)
    assert isinstance(specification_url, str)
    if len(specification_url.encode("ascii")) > uint16.maximum:
        raise ValueError("specification_url cannot exceed 65535 bytes")


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One versioned stage and its opaque, stage-owned parameters."""

    stage_id: str
    parameters: bytes = b""

    def __post_init__(self) -> None:
        _require_bytes("stage parameters", self.parameters)
        validate_extension_id(self.stage_id)
        uint32.require("stage parameter size", len(self.parameters))


@dataclass(frozen=True, slots=True)
class ExtensionDeclaration:
    """One referenced extension and optional untrusted specification URL."""

    extension_id: str
    specification_url: str | None = None

    def __post_init__(self) -> None:
        validate_extension_id(self.extension_id)
        if self.specification_url is not None:
            _validate_wire_specification_url(self.specification_url)


@dataclass(frozen=True, slots=True)
class Recipe:
    """A reusable, possibly empty linear processing pipeline."""

    recipe_id: int
    stages: tuple[StageSpec, ...]

    def __post_init__(self) -> None:
        _require_tuple("recipe stages", self.stages, StageSpec)
        uint32.require("recipe_id", self.recipe_id)
        if len(self.stages) > uint16.maximum:
            raise ValueError("a recipe cannot contain more than 65535 stages")


@dataclass(frozen=True, slots=True)
class Stream:
    """A logical stream declaration from the manifest."""

    stream_id: int
    stream_type: str
    default_recipe_id: int
    metadata: bytes = b""

    def __post_init__(self) -> None:
        _require_bytes("stream metadata", self.metadata)
        uint32.require("stream_id", self.stream_id)
        validate_extension_id(self.stream_type)
        uint32.require("default_recipe_id", self.default_recipe_id)
        uint32.require("stream metadata size", len(self.metadata))


@dataclass(frozen=True, slots=True)
class Manifest:
    """Definitions required to inspect and decode an OBST container."""

    recipes: tuple[Recipe, ...]
    streams: tuple[Stream, ...]
    extensions: tuple[ExtensionDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _require_tuple("manifest recipes", self.recipes, Recipe)
        _require_tuple("manifest streams", self.streams, Stream)
        _require_tuple("manifest extensions", self.extensions, ExtensionDeclaration)
        if not self.recipes:
            raise ValueError("a manifest must declare at least one recipe")
        if not self.streams:
            raise ValueError("a manifest must declare at least one stream")
        recipe_ids = {recipe.recipe_id for recipe in self.recipes}
        if len(recipe_ids) != len(self.recipes):
            raise ValueError("recipe ids must be unique")

        stream_ids = {stream.stream_id for stream in self.streams}
        if len(stream_ids) != len(self.streams):
            raise ValueError("stream ids must be unique")
        for stream in self.streams:
            if stream.default_recipe_id not in recipe_ids:
                raise ValueError(
                    f"stream {stream.stream_id} references unknown default recipe "
                    f"{stream.default_recipe_id}"
                )

        stream_type_ids = {stream.stream_type for stream in self.streams}
        stage_ids = {
            stage.stage_id for recipe in self.recipes for stage in recipe.stages
        }
        shared_ids = stream_type_ids & stage_ids
        if shared_ids:
            extension_id = min(shared_ids)
            raise ValueError(
                "extension id cannot identify both a Stage and a stream type: "
                f"{extension_id}"
            )
        referenced_ids = stream_type_ids | stage_ids
        declared_by_id = {
            declaration.extension_id: declaration for declaration in self.extensions
        }
        if len(declared_by_id) != len(self.extensions):
            raise ValueError("extension declarations must be unique")
        undeclared_references = set(declared_by_id) - referenced_ids
        if undeclared_references:
            extension_id = min(undeclared_references)
            raise ValueError(f"extension declaration is not referenced: {extension_id}")
        object.__setattr__(
            self,
            "extensions",
            tuple(
                declared_by_id.get(extension_id, ExtensionDeclaration(extension_id))
                for extension_id in sorted(referenced_ids)
            ),
        )

    def recipe(self, recipe_id: int) -> Recipe:
        """Return one declared recipe or raise a structural error."""
        for recipe in self.recipes:
            if recipe.recipe_id == recipe_id:
                return recipe
        raise KeyError(recipe_id)

    def stream(self, stream_id: int) -> Stream:
        """Return one declared stream or raise a structural error."""
        for stream in self.streams:
            if stream.stream_id == stream_id:
                return stream
        raise KeyError(stream_id)

    def extension_ids(self) -> tuple[str, ...]:
        """Return the deterministic set of required stream types and stages."""
        return tuple(extension.extension_id for extension in self.extensions)

    def extension(self, extension_id: str) -> ExtensionDeclaration:
        """Return one referenced extension declaration."""
        for extension in self.extensions:
            if extension.extension_id == extension_id:
                return extension
        raise KeyError(extension_id)

    def stage_ids(self) -> tuple[str, ...]:
        """Return the deterministic set of stage IDs used by recipes."""
        return tuple(
            sorted(
                {stage.stage_id for recipe in self.recipes for stage in recipe.stages}
            )
        )


@dataclass(frozen=True, slots=True)
class Chunk:
    """One validated chunk containing its still-encoded payload."""

    stream_id: int
    sequence: int
    recipe_id: int
    logical_size: int
    logical_hash: bytes
    encoded_payload: bytes

    def __post_init__(self) -> None:
        _require_bytes("logical hash", self.logical_hash)
        _require_bytes("encoded payload", self.encoded_payload)
        uint32.require("stream_id", self.stream_id)
        uint64.require("sequence", self.sequence)
        uint32.require("recipe_id", self.recipe_id)
        uint64.require("logical_size", self.logical_size)
        if len(self.logical_hash) != BLAKE2S_128_SIZE:
            raise ValueError(
                f"logical hash must contain exactly {BLAKE2S_128_SIZE} bytes"
            )
        uint64.require("encoded_size", len(self.encoded_payload))

    @property
    def encoded_size(self) -> int:
        return len(self.encoded_payload)
