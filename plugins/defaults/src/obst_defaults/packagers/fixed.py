# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Shipped deterministic fixed-recipe packaging policy."""

from __future__ import annotations

from dataclasses import dataclass

from obst.core import (
    CoreResource,
    ResourceAccounting,
)
from obst.core.container import ContainerWriter
from obst.core.errors import OperationStateError, PackagingError
from obst.core.extensions import ExtensionDescriptor, ExtensionKind
from obst.core.io import BinaryWriter
from obst.core.manifest import validate_manifest_resources
from obst.core.model import ExtensionDeclaration, Manifest, Recipe, Stream
from obst.core.packaging import (
    LogicalStreamSource,
    PackagedStream,
    PackageResult,
    PackageWriteOperation,
    RecipeSpec,
)
from obst.core.registry import ExtensionRegistry
from obst.core.streams import ChunkEncoder


@dataclass(frozen=True, slots=True)
class FixedPackageRequest:
    """Select exact logical sources, capabilities and limits for fixed packaging."""

    registry: ExtensionRegistry
    sources: tuple[LogicalStreamSource, ...]
    accounting: ResourceAccounting

    def __post_init__(self) -> None:
        if type(self.registry) is not ExtensionRegistry:
            raise TypeError("fixed package registry must be an ExtensionRegistry")
        if type(self.sources) is not tuple:
            raise TypeError("fixed package sources must be a tuple")
        if not all(type(source) is LogicalStreamSource for source in self.sources):
            raise TypeError(
                "fixed package sources must contain LogicalStreamSource values"
            )
        if type(self.accounting) is not ResourceAccounting:
            raise TypeError("fixed package accounting must be ResourceAccounting")


class FixedPackagerExtension:
    """Provide deterministic packaging with each source's declared recipe."""

    extension_id = "obst.fixed@1"
    kind = ExtensionKind.PACKAGER
    descriptor = ExtensionDescriptor(
        display_name="Fixed packager",
        summary="Package each logical source once with its declared fixed recipe.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/packagers/fixed.md"
        ),
    )

    def prepare_package(
        self,
        request: FixedPackageRequest,
        /,
    ) -> PackageWriteOperation:
        if type(request) is not FixedPackageRequest:
            raise PackagingError("fixed packager requires FixedPackageRequest")
        return _FixedPackageOperation(request)


class _FixedPackageOperation:
    def __init__(self, request: FixedPackageRequest) -> None:
        self._request = request
        self._consumed = False

    def write_to(self, target: BinaryWriter, /) -> PackageResult:
        if self._consumed:
            raise OperationStateError("write package", "consumed")
        self._consumed = True
        sources = self._request.sources
        if not sources:
            raise PackagingError("at least one logical stream source is required")
        if len({id(source) for source in sources}) != len(sources):
            raise PackagingError("a logical stream source cannot be declared twice")
        for source in sources:
            _preflight_source(source, self._request.accounting)
        plan = _fixed_package_plan(sources, self._request.registry)
        manifest = plan.manifest
        validate_manifest_resources(manifest, accounting=self._request.accounting)
        encoder = ChunkEncoder(
            self._request.registry,
            accounting=self._request.accounting,
        )
        encoder.preflight(manifest.recipes)
        writer = ContainerWriter(
            target,
            manifest,
            accounting=self._request.accounting,
        )
        packaged_streams: list[PackagedStream] = []
        for stream, source, recipe in zip(
            manifest.streams,
            sources,
            plan.stream_recipes,
            strict=True,
        ):
            chunk_count = 0
            logical_size = 0
            for sequence, logical_chunk in enumerate(source.iter_chunks()):
                writer.preflight_chunk(len(logical_chunk))
                writer.write_chunk(
                    encoder.encode(
                        logical_chunk,
                        stream_id=stream.stream_id,
                        sequence=sequence,
                        recipe=recipe,
                    )
                )
                chunk_count += 1
                logical_size += len(logical_chunk)
            packaged_streams.append(PackagedStream(stream, chunk_count, logical_size))
        write_result = writer.finish()
        return PackageResult(
            manifest=manifest,
            encoded_size=write_result.encoded_size,
            chunk_count=write_result.chunk_count,
            streams=tuple(packaged_streams),
        )


@dataclass(frozen=True, slots=True)
class _FixedPackagePlan:
    manifest: Manifest
    stream_recipes: tuple[Recipe, ...]


def _fixed_package_plan(
    sources: tuple[LogicalStreamSource, ...],
    registry: ExtensionRegistry,
) -> _FixedPackagePlan:
    recipe_ids: dict[RecipeSpec, int] = {}
    recipes: list[Recipe] = []
    streams: list[Stream] = []
    stream_recipes: list[Recipe] = []
    for stream_id, source in enumerate(sources):
        descriptor = source.descriptor
        recipe_id = recipe_ids.get(descriptor.recipe)
        if recipe_id is None:
            recipe_id = len(recipe_ids)
            recipe_ids[descriptor.recipe] = recipe_id
            recipes.append(Recipe(recipe_id, descriptor.recipe.stages))
        stream_recipes.append(recipes[recipe_id])
        streams.append(
            Stream(
                stream_id=stream_id,
                stream_type=descriptor.stream_type,
                metadata=descriptor.metadata,
            )
        )
    referenced_ids = {stream.stream_type for stream in streams}
    referenced_ids.update(
        stage.stage_id for recipe in recipes for stage in recipe.stages
    )
    extensions = tuple(
        ExtensionDeclaration(
            extension_id,
            (
                None
                if (extension_descriptor := registry.get_descriptor(extension_id))
                is None
                else extension_descriptor.specification_url
            ),
        )
        for extension_id in sorted(referenced_ids)
    )
    return _FixedPackagePlan(
        Manifest(
            recipes=tuple(recipes),
            streams=tuple(streams),
            extensions=extensions,
        ),
        tuple(stream_recipes),
    )


def _preflight_source(
    source: LogicalStreamSource,
    accounting: ResourceAccounting,
) -> None:
    scope = f"logical source {source.descriptor.stream_type}"
    accounting.check(
        CoreResource.LOGICAL_CHUNK_BYTES,
        source.max_chunk_bytes,
        scope=scope,
        phase="package",
    )
    accounting.check(
        CoreResource.INTERMEDIATE_BYTES,
        source.max_chunk_bytes,
        scope=scope,
        phase="package",
    )
