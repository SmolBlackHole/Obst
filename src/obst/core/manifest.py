"""Canonical core encoding for the OBST v0 manifest."""

from __future__ import annotations

import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from obst.core.errors import (
    CorruptContainerError,
    InvalidContainerError,
    UnknownRecipeError,
    UnknownStreamError,
)
from obst.core.io import Cursor
from obst.core.model import (
    ExtensionDeclaration,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
)
from obst.core.resource_accounting import (
    CoreResource,
    ResourceAccounting,
)
from obst.core.wire import (
    ManifestHeader,
    extension_declaration,
    recipe_declaration,
    stage_declaration,
    stream_declaration,
    uint16,
    uint32,
)


@dataclass(frozen=True, slots=True)
class ManifestIndex:
    """Immutable exact lookup over one already validated manifest."""

    manifest: Manifest
    _recipes: Mapping[int, Recipe] = field(init=False, repr=False)
    _streams: Mapping[int, Stream] = field(init=False, repr=False)
    _extensions: Mapping[str, ExtensionDeclaration] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.manifest) is not Manifest:
            raise TypeError("manifest index requires an exact Manifest")
        object.__setattr__(
            self,
            "_recipes",
            MappingProxyType(
                {recipe.recipe_id: recipe for recipe in self.manifest.recipes}
            ),
        )
        object.__setattr__(
            self,
            "_streams",
            MappingProxyType(
                {stream.stream_id: stream for stream in self.manifest.streams}
            ),
        )
        object.__setattr__(
            self,
            "_extensions",
            MappingProxyType(
                {
                    extension.extension_id: extension
                    for extension in self.manifest.extensions
                }
            ),
        )

    def recipe(self, recipe_id: int) -> Recipe:
        """Return one declared recipe or raise the public selection error."""
        try:
            return self._recipes[recipe_id]
        except KeyError as exc:
            raise UnknownRecipeError(recipe_id) from exc

    def stream(self, stream_id: int) -> Stream:
        """Return one declared stream or raise the public selection error."""
        try:
            return self._streams[stream_id]
        except KeyError as exc:
            raise UnknownStreamError(stream_id) from exc

    def extension(self, extension_id: str) -> ExtensionDeclaration:
        """Return one declared extension using ordinary mapping absence semantics."""
        return self._extensions[extension_id]


def encode_manifest(
    manifest: Manifest,
    *,
    accounting: ResourceAccounting,
) -> bytes:
    """Encode one manifest after proving it fits the supplied byte budget."""
    _require_accounting(accounting)
    extension_indexes, expected_size = _manifest_encoding_context(
        manifest,
        accounting=accounting,
    )
    body = bytearray()
    for part in _iter_body_parts(manifest, extension_indexes):
        body.extend(part)
    body_bytes = bytes(body)
    header = ManifestHeader(
        extension_count=len(extension_indexes),
        body_size=len(body_bytes),
        body_crc32=zlib.crc32(body_bytes),
    ).encode()
    encoded = header + body_bytes
    assert len(encoded) == expected_size
    return encoded


def validate_manifest_resources(
    manifest: Manifest,
    *,
    accounting: ResourceAccounting,
) -> None:
    """Refuse a manifest outside local policy without constructing its body."""
    _require_accounting(accounting)
    _manifest_encoding_context(manifest, accounting=accounting)


def _iter_body_parts(
    manifest: Manifest,
    extension_indexes: dict[str, int],
) -> Iterator[bytes]:
    for extension in manifest.extensions:
        encoded_id = extension.extension_id.encode("ascii")
        encoded_url = (
            b""
            if extension.specification_url is None
            else extension.specification_url.encode("ascii")
        )
        if len(encoded_id) > uint16.maximum:
            raise ValueError("extension id cannot exceed 65535 bytes")
        yield extension_declaration.pack(len(encoded_id), len(encoded_url))
        yield encoded_id
        yield encoded_url

    for recipe in sorted(manifest.recipes, key=lambda item: item.recipe_id):
        yield recipe_declaration.pack(
            recipe.recipe_id,
            len(recipe.stages),
            0,
        )
        for stage in recipe.stages:
            yield stage_declaration.pack(
                extension_indexes[stage.stage_id],
                len(stage.parameters),
            )
            yield stage.parameters

    for stream in sorted(manifest.streams, key=lambda item: item.stream_id):
        yield stream_declaration.pack(
            stream.stream_id,
            extension_indexes[stream.stream_type],
            stream.default_recipe_id,
            len(stream.metadata),
        )
        yield stream.metadata


def _require_encoded_size(
    manifest: Manifest,
    extension_indexes: dict[str, int],
    *,
    accounting: ResourceAccounting,
) -> int:
    total_size = ManifestHeader.size
    _require_manifest_wire_size(total_size)
    accounting.record(
        CoreResource.MANIFEST_BYTES,
        total_size,
        scope="manifest",
        phase="manifest_encode",
    )
    for part in _iter_body_parts(manifest, extension_indexes):
        total_size += len(part)
        _require_manifest_wire_size(total_size)
        accounting.record(
            CoreResource.MANIFEST_BYTES,
            total_size,
            scope="manifest",
            phase="manifest_encode",
        )
    return total_size


def _require_manifest_wire_size(total_size: int) -> None:
    uint32.require("complete manifest size", total_size)


def validate_manifest_counts(
    *,
    recipe_count: int,
    stream_count: int,
    accounting: ResourceAccounting,
    phase: str = "manifest_decode",
) -> None:
    """Reject declared manifest counts outside one reader policy."""
    accounting.record(
        CoreResource.RECIPES,
        recipe_count,
        scope="manifest",
        phase=phase,
    )
    accounting.record(
        CoreResource.STREAMS,
        stream_count,
        scope="manifest",
        phase=phase,
    )


def validate_manifest_header(
    header: ManifestHeader,
    *,
    manifest_size: int,
    accounting: ResourceAccounting,
    phase: str = "manifest_decode",
) -> None:
    """Validate declared manifest framing and Extension count policy."""
    if type(header) is not ManifestHeader:
        raise TypeError("manifest header must be an exact ManifestHeader")
    if manifest_size < ManifestHeader.size:
        raise InvalidContainerError("manifest is shorter than its fixed header")
    if header.body_size != manifest_size - ManifestHeader.size:
        raise InvalidContainerError(
            "manifest body size does not match container header"
        )
    accounting.record(
        CoreResource.EXTENSIONS,
        header.extension_count,
        scope="manifest",
        phase=phase,
    )


def decode_manifest(
    data: bytes,
    *,
    recipe_count: int,
    stream_count: int,
    accounting: ResourceAccounting,
) -> Manifest:
    """Decode and validate an exact manifest byte string."""
    _require_accounting(accounting)
    accounting.record(
        CoreResource.MANIFEST_BYTES,
        len(data),
        scope="manifest",
        phase="manifest_decode",
    )
    validate_manifest_counts(
        recipe_count=recipe_count,
        stream_count=stream_count,
        accounting=accounting,
    )
    if len(data) < ManifestHeader.size:
        raise InvalidContainerError("manifest is shorter than its fixed header")

    header = ManifestHeader.decode(data[: ManifestHeader.size])
    body = data[ManifestHeader.size :]
    validate_manifest_header(
        header,
        manifest_size=len(data),
        accounting=accounting,
    )
    return _decode_manifest_body(
        header,
        body,
        recipe_count=recipe_count,
        stream_count=stream_count,
        accounting=accounting,
    )


def decode_manifest_parts(
    header: ManifestHeader,
    body: bytes,
    *,
    recipe_count: int,
    stream_count: int,
    accounting: ResourceAccounting,
) -> Manifest:
    """Decode one validated fixed header and its exact manifest body."""
    manifest_size = ManifestHeader.size + len(body)
    _require_accounting(accounting)
    accounting.record(
        CoreResource.MANIFEST_BYTES,
        manifest_size,
        scope="manifest",
        phase="manifest_decode",
    )
    validate_manifest_counts(
        recipe_count=recipe_count,
        stream_count=stream_count,
        accounting=accounting,
    )
    validate_manifest_header(
        header,
        manifest_size=manifest_size,
        accounting=accounting,
    )
    return _decode_manifest_body(
        header,
        body,
        recipe_count=recipe_count,
        stream_count=stream_count,
        accounting=accounting,
    )


def _require_accounting(accounting: object) -> None:
    if type(accounting) is not ResourceAccounting:
        raise TypeError("manifest accounting must be ResourceAccounting")


def _decode_manifest_body(
    header: ManifestHeader,
    body: bytes,
    *,
    recipe_count: int,
    stream_count: int,
    accounting: ResourceAccounting,
) -> Manifest:
    if zlib.crc32(body) != header.body_crc32:
        raise CorruptContainerError("manifest body checksum mismatch")

    cursor = Cursor(body)
    extensions = _decode_extensions(cursor, header.extension_count)
    extension_ids = tuple(extension.extension_id for extension in extensions)
    recipes: list[Recipe] = []
    total_stage_count = 0
    for _ in range(recipe_count):
        recipe = _decode_recipe(
            cursor,
            extension_ids,
            accounting=accounting,
            total_stage_count=total_stage_count,
        )
        recipes.append(recipe)
        total_stage_count += len(recipe.stages)
    streams = tuple(_decode_stream(cursor, extension_ids) for _ in range(stream_count))
    cursor.ensure_finished(structure="manifest")
    if tuple(recipe.recipe_id for recipe in recipes) != tuple(
        sorted(recipe.recipe_id for recipe in recipes)
    ):
        raise InvalidContainerError("recipes must be sorted by id")
    if tuple(stream.stream_id for stream in streams) != tuple(
        sorted(stream.stream_id for stream in streams)
    ):
        raise InvalidContainerError("streams must be sorted by id")

    try:
        return Manifest(
            recipes=tuple(recipes),
            streams=streams,
            extensions=extensions,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidContainerError(f"invalid manifest model: {exc}") from exc


def _decode_extensions(cursor: Cursor, count: int) -> tuple[ExtensionDeclaration, ...]:
    extensions: list[ExtensionDeclaration] = []
    for _ in range(count):
        id_size, url_size = cursor.unpack(
            extension_declaration,
            field="extension declaration",
        )
        raw_id = cursor.take(id_size, field="extension id")
        raw_url = cursor.take(url_size, field="extension specification URL")
        try:
            extension_id = raw_id.decode("ascii")
            specification_url = raw_url.decode("ascii") if raw_url else None
            declaration = ExtensionDeclaration(extension_id, specification_url)
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidContainerError(
                f"invalid extension declaration: {exc}"
            ) from exc
        extensions.append(declaration)
    extension_ids = [extension.extension_id for extension in extensions]
    if extension_ids != sorted(set(extension_ids)):
        raise InvalidContainerError("extension ids must be unique and sorted")
    return tuple(extensions)


def _extension_at(extension_ids: tuple[str, ...], index: int) -> str:
    try:
        return extension_ids[index]
    except IndexError as exc:
        raise InvalidContainerError(f"unknown extension index {index}") from exc


def _decode_recipe(
    cursor: Cursor,
    extension_ids: tuple[str, ...],
    *,
    accounting: ResourceAccounting,
    total_stage_count: int,
) -> Recipe:
    recipe_id, stage_count, reserved = cursor.unpack(
        recipe_declaration,
        field="recipe declaration",
    )
    if reserved != 0:
        raise InvalidContainerError("recipe reserved field must be zero")
    accounting.record(
        CoreResource.STAGES_PER_RECIPE,
        stage_count,
        scope=f"recipe {recipe_id}",
        phase="manifest_decode",
    )
    accounting.record(
        CoreResource.TOTAL_STAGES,
        total_stage_count + stage_count,
        scope="manifest",
        phase="manifest_decode",
    )
    stages: list[StageSpec] = []
    for _ in range(stage_count):
        extension_index, parameter_size = cursor.unpack(
            stage_declaration,
            field="stage declaration",
        )
        parameters = cursor.take(parameter_size, field="stage parameters")
        stages.append(
            StageSpec(_extension_at(extension_ids, extension_index), parameters)
        )
    try:
        return Recipe(recipe_id, tuple(stages))
    except ValueError as exc:
        raise InvalidContainerError(f"invalid recipe: {exc}") from exc


def _validate_manifest_model_counts(
    manifest: Manifest,
    *,
    accounting: ResourceAccounting,
    phase: str,
) -> None:
    validate_manifest_counts(
        recipe_count=len(manifest.recipes),
        stream_count=len(manifest.streams),
        accounting=accounting,
        phase=phase,
    )
    accounting.record(
        CoreResource.EXTENSIONS,
        len(manifest.extensions),
        scope="manifest",
        phase=phase,
    )
    total_stages = 0
    for recipe in manifest.recipes:
        stage_count = len(recipe.stages)
        accounting.record(
            CoreResource.STAGES_PER_RECIPE,
            stage_count,
            scope=f"recipe {recipe.recipe_id}",
            phase=phase,
        )
        total_stages += stage_count
        accounting.record(
            CoreResource.TOTAL_STAGES,
            total_stages,
            scope="manifest",
            phase=phase,
        )


def _manifest_encoding_context(
    manifest: Manifest,
    *,
    accounting: ResourceAccounting,
) -> tuple[dict[str, int], int]:
    _validate_manifest_model_counts(
        manifest,
        accounting=accounting,
        phase="manifest_encode",
    )
    extension_indexes = {
        extension_id: index
        for index, extension_id in enumerate(manifest.extension_ids())
    }
    expected_size = _require_encoded_size(
        manifest,
        extension_indexes,
        accounting=accounting,
    )
    return extension_indexes, expected_size


def _decode_stream(cursor: Cursor, extension_ids: tuple[str, ...]) -> Stream:
    stream_id, type_index, recipe_id, metadata_size = cursor.unpack(
        stream_declaration,
        field="stream declaration",
    )
    metadata = cursor.take(metadata_size, field="stream metadata")
    try:
        return Stream(
            stream_id=stream_id,
            stream_type=_extension_at(extension_ids, type_index),
            default_recipe_id=recipe_id,
            metadata=metadata,
        )
    except ValueError as exc:
        raise InvalidContainerError(f"invalid stream: {exc}") from exc
