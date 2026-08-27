"""Complete core inspection of one consumed OBST container."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from obst.core.container import ContainerReader, ContainerSummary
from obst.core.errors import ExtensionContractError
from obst.core.extensions import InspectionInterpretation
from obst.core.model import Manifest, Recipe, StageSpec, Stream, validate_extension_id
from obst.core.registry import ExtensionRegistry
from obst.core.wire import FormatVersion


@dataclass(frozen=True, slots=True)
class RecipeChunkUsage:
    """Actual number of chunks referencing one recipe."""

    recipe_id: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class InspectedStage:
    """One raw stage declaration plus optional parameter interpretation."""

    spec: StageSpec
    parameters: InspectionInterpretation | None


@dataclass(frozen=True, slots=True)
class InspectedRecipe:
    """One raw recipe declaration with actual chunk usage."""

    declaration: Recipe
    stages: tuple[InspectedStage, ...]
    chunk_count: int


@dataclass(frozen=True, slots=True)
class InspectedStream:
    """One raw stream declaration with structural usage and sizes."""

    declaration: Stream
    metadata: InspectionInterpretation | None
    chunk_count: int
    logical_size: int
    encoded_payload_size: int
    recipe_usage: tuple[RecipeChunkUsage, ...]


@dataclass(frozen=True, slots=True)
class InspectedStageCapability:
    """Declared and actually required local capability for one stage contract."""

    stage_id: str
    declared_recipe_ids: tuple[int, ...]
    used_chunks_by_recipe: tuple[RecipeChunkUsage, ...]
    decoder_available: bool
    declared_specification_url: str | None
    display_name: str | None
    summary: str | None
    local_specification_url: str | None

    @property
    def used_recipe_ids(self) -> tuple[int, ...]:
        return tuple(usage.recipe_id for usage in self.used_chunks_by_recipe)

    @property
    def chunk_count(self) -> int:
        return sum(usage.chunk_count for usage in self.used_chunks_by_recipe)

    @property
    def required(self) -> bool:
        return bool(self.used_chunks_by_recipe)


class LogicalRecoveryStatus(StrEnum):
    """Whether logical payload recovery was attempted by an operation."""

    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True, slots=True)
class InspectionInterpretationPolicy:
    """Host-approved extension IDs whose interpreters inspection may invoke."""

    extension_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.extension_ids) is not frozenset:
            raise TypeError("extension_ids must be an exact frozenset")
        for extension_id in self.extension_ids:
            if type(extension_id) is not str:
                raise TypeError("extension_ids must contain only exact strings")
            validate_extension_id(extension_id)

    def allows(self, extension_id: str) -> bool:
        """Return whether inspection may invoke this extension's interpreter."""
        return extension_id in self.extension_ids


@dataclass(frozen=True, slots=True)
class ContainerResourceFootprint:
    """Exact representation facts relevant to local resource policy."""

    manifest_size: int
    extension_count: int
    recipe_count: int
    stream_count: int
    total_stage_count: int
    max_stages_per_recipe: int
    max_encoded_chunk_size: int
    max_logical_chunk_size: int
    stage_executions: int
    max_materialized_stream_size: int


@dataclass(frozen=True, slots=True)
class ContainerInspection:
    """Authoritative result of one complete structural read session."""

    version: FormatVersion
    manifest: Manifest
    streams: tuple[InspectedStream, ...]
    recipes: tuple[InspectedRecipe, ...]
    stage_capabilities: tuple[InspectedStageCapability, ...]
    summary: ContainerSummary
    resources: ContainerResourceFootprint
    interpretation_policy: InspectionInterpretationPolicy
    logical_recovery: LogicalRecoveryStatus = LogicalRecoveryStatus.NOT_ATTEMPTED

    @property
    def stream_count(self) -> int:
        return len(self.manifest.streams)

    @property
    def recipe_count(self) -> int:
        return len(self.manifest.recipes)

    @property
    def encoded_size(self) -> int:
        return self.summary.encoded_size

    @property
    def chunk_count(self) -> int:
        return self.summary.chunk_count

    @property
    def logical_size(self) -> int:
        return self.summary.logical_size

    @property
    def encoded_payload_size(self) -> int:
        return self.summary.encoded_payload_size

    @property
    def encoded_to_logical_ratio(self) -> float | None:
        if self.logical_size == 0:
            return None
        return self.encoded_size / self.logical_size

    @property
    def missing_declared_stages(self) -> tuple[str, ...]:
        return tuple(
            stage.stage_id
            for stage in self.stage_capabilities
            if not stage.decoder_available
        )

    @property
    def missing_required_stages(self) -> tuple[str, ...]:
        return tuple(
            stage.stage_id
            for stage in self.stage_capabilities
            if stage.required and not stage.decoder_available
        )

    @property
    def required_decoders_available(self) -> bool:
        return not self.missing_required_stages


def inspect_container(
    reader: ContainerReader,
    *,
    registry: ExtensionRegistry | None = None,
    interpretation_policy: InspectionInterpretationPolicy | None = None,
) -> ContainerInspection:
    """Consume a reader without decoding or implicitly invoking interpreters."""
    effective_registry = ExtensionRegistry() if registry is None else registry
    effective_interpretation_policy = (
        InspectionInterpretationPolicy()
        if interpretation_policy is None
        else interpretation_policy
    )
    stream_stats = {
        stream.stream_id: _MutableStreamStats() for stream in reader.manifest.streams
    }
    recipe_chunk_counts = {recipe.recipe_id: 0 for recipe in reader.manifest.recipes}
    max_encoded_chunk_size = 0
    max_logical_chunk_size = 0
    for chunk in reader.iter_chunks():
        max_encoded_chunk_size = max(max_encoded_chunk_size, chunk.encoded_size)
        max_logical_chunk_size = max(max_logical_chunk_size, chunk.logical_size)
        stats = stream_stats[chunk.stream_id]
        stats.chunk_count += 1
        stats.logical_size += chunk.logical_size
        stats.encoded_payload_size += chunk.encoded_size
        stats.recipe_chunk_counts[chunk.recipe_id] = (
            stats.recipe_chunk_counts.get(chunk.recipe_id, 0) + 1
        )
        recipe_chunk_counts[chunk.recipe_id] += 1

    streams = tuple(
        InspectedStream(
            declaration=stream,
            metadata=_interpret_stream_metadata(
                effective_registry,
                effective_interpretation_policy,
                stream,
            ),
            chunk_count=stream_stats[stream.stream_id].chunk_count,
            logical_size=stream_stats[stream.stream_id].logical_size,
            encoded_payload_size=(stream_stats[stream.stream_id].encoded_payload_size),
            recipe_usage=tuple(
                RecipeChunkUsage(recipe_id, count)
                for recipe_id, count in sorted(
                    stream_stats[stream.stream_id].recipe_chunk_counts.items()
                )
            ),
        )
        for stream in reader.manifest.streams
    )
    recipes = tuple(
        InspectedRecipe(
            declaration=recipe,
            stages=tuple(
                InspectedStage(
                    spec=stage,
                    parameters=_interpret_stage_parameters(
                        effective_registry,
                        effective_interpretation_policy,
                        stage,
                    ),
                )
                for stage in recipe.stages
            ),
            chunk_count=recipe_chunk_counts[recipe.recipe_id],
        )
        for recipe in reader.manifest.recipes
    )
    declared_recipes_by_stage = _declared_recipes_by_stage(reader.manifest)
    stage_capabilities = tuple(
        _stage_capability(
            reader.manifest,
            effective_registry,
            stage_id,
            recipe_ids,
            recipe_chunk_counts,
        )
        for stage_id, recipe_ids in declared_recipes_by_stage.items()
    )
    total_stage_count = sum(len(recipe.stages) for recipe in reader.manifest.recipes)
    summary = reader.summary
    resources = ContainerResourceFootprint(
        manifest_size=reader.manifest_size,
        extension_count=len(reader.manifest.extensions),
        recipe_count=len(reader.manifest.recipes),
        stream_count=len(reader.manifest.streams),
        total_stage_count=total_stage_count,
        max_stages_per_recipe=max(
            (len(recipe.stages) for recipe in reader.manifest.recipes),
            default=0,
        ),
        max_encoded_chunk_size=max_encoded_chunk_size,
        max_logical_chunk_size=max_logical_chunk_size,
        stage_executions=sum(
            recipe_chunk_counts[recipe.recipe_id] * len(recipe.stages)
            for recipe in reader.manifest.recipes
        ),
        max_materialized_stream_size=max(
            (stream.logical_size for stream in streams),
            default=0,
        ),
    )
    return ContainerInspection(
        version=reader.version,
        manifest=reader.manifest,
        streams=streams,
        recipes=recipes,
        stage_capabilities=stage_capabilities,
        summary=summary,
        resources=resources,
        interpretation_policy=effective_interpretation_policy,
    )


@dataclass(slots=True)
class _MutableStreamStats:
    chunk_count: int = 0
    logical_size: int = 0
    encoded_payload_size: int = 0
    recipe_chunk_counts: dict[int, int] = field(default_factory=lambda: {})


def _interpret_stream_metadata(
    registry: ExtensionRegistry,
    policy: InspectionInterpretationPolicy,
    stream: Stream,
) -> InspectionInterpretation | None:
    if not policy.allows(stream.stream_type):
        return None
    interpreter = registry.get_stream_metadata_interpreter(stream.stream_type)
    if interpreter is None:
        return None
    return _invoke_interpreter(
        stream.stream_type,
        "metadata interpreter",
        interpreter.interpret_metadata,
        stream.metadata,
    )


def _interpret_stage_parameters(
    registry: ExtensionRegistry,
    policy: InspectionInterpretationPolicy,
    stage: StageSpec,
) -> InspectionInterpretation | None:
    if not policy.allows(stage.stage_id):
        return None
    interpreter = registry.get_stage_parameter_interpreter(stage.stage_id)
    if interpreter is None:
        return None
    return _invoke_interpreter(
        stage.stage_id,
        "parameter interpreter",
        interpreter.interpret_parameters,
        stage.parameters,
    )


def _invoke_interpreter(
    extension_id: str,
    capability: str,
    operation: Callable[[bytes], InspectionInterpretation],
    data: bytes,
) -> InspectionInterpretation:
    try:
        result = operation(data)
    except Exception as exc:
        raise ExtensionContractError(
            extension_id,
            capability,
            f"provider raised {type(exc).__name__}: {exc}",
        ) from exc
    if type(result) is not InspectionInterpretation:
        raise ExtensionContractError(
            extension_id,
            capability,
            "provider must return an exact InspectionInterpretation",
        )
    try:
        InspectionInterpretation(result.label, result.fields, result.error)
    except (TypeError, ValueError) as exc:
        raise ExtensionContractError(
            extension_id,
            capability,
            f"provider returned invalid InspectionInterpretation: {exc}",
        ) from exc
    return result


def _declared_recipes_by_stage(manifest: Manifest) -> Mapping[str, tuple[int, ...]]:
    mutable: dict[str, list[int]] = {}
    for recipe in manifest.recipes:
        for stage_id in {stage.stage_id for stage in recipe.stages}:
            mutable.setdefault(stage_id, []).append(recipe.recipe_id)
    return {
        stage_id: tuple(sorted(recipe_ids))
        for stage_id, recipe_ids in sorted(mutable.items())
    }


def _stage_capability(
    manifest: Manifest,
    registry: ExtensionRegistry,
    stage_id: str,
    declared_recipe_ids: tuple[int, ...],
    recipe_chunk_counts: Mapping[int, int],
) -> InspectedStageCapability:
    descriptor = registry.get_descriptor(stage_id)
    declaration = manifest.extension(stage_id)
    return InspectedStageCapability(
        stage_id=stage_id,
        declared_recipe_ids=declared_recipe_ids,
        used_chunks_by_recipe=tuple(
            RecipeChunkUsage(recipe_id, recipe_chunk_counts[recipe_id])
            for recipe_id in declared_recipe_ids
            if recipe_chunk_counts[recipe_id] > 0
        ),
        decoder_available=registry.can_decode(stage_id),
        declared_specification_url=declaration.specification_url,
        display_name=None if descriptor is None else descriptor.display_name,
        summary=None if descriptor is None else descriptor.summary,
        local_specification_url=None
        if descriptor is None
        else descriptor.specification_url,
    )
