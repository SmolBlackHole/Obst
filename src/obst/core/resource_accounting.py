"""Public operation-local accounting for the OBST reference runtime."""

from __future__ import annotations

from typing import Final, cast

from obst.core.errors import ObstError
from obst.resources import (
    DEFAULT_LIMIT_PROFILE,
    ResourceAggregation,
    ResourceCatalog,
    ResourceDefinition,
    ResourceKind,
    ResourcePolicy,
    ResourceUnit,
)

__all__ = [
    "DEFAULT_RESOURCE_CATALOG",
    "DEFAULT_RESOURCE_POLICY",
    "CoreResource",
    "ResourceAccounting",
    "ResourceLimitError",
]

_MIB = 1024 * 1024
_GIB = 1024 * _MIB


class CoreResource(ResourceKind):
    """Closed set of local resources measured by the OBST Core runtime."""

    MANIFEST_BYTES = ResourceDefinition(
        "manifest_bytes",
        16 * _MIB,
        "Bytes in one encoded manifest.",
        ResourceUnit.BYTES,
        ResourceAggregation.PEAK,
    )
    ENCODED_CHUNK_BYTES = ResourceDefinition(
        "encoded_chunk_bytes",
        64 * _MIB,
        "Encoded bytes in one chunk.",
        ResourceUnit.BYTES,
        ResourceAggregation.PEAK,
    )
    LOGICAL_CHUNK_BYTES = ResourceDefinition(
        "logical_chunk_bytes",
        64 * _MIB,
        "Logical bytes in one chunk.",
        ResourceUnit.BYTES,
        ResourceAggregation.PEAK,
    )
    INTERMEDIATE_BYTES = ResourceDefinition(
        "intermediate_bytes",
        64 * _MIB,
        "Bytes in one pipeline intermediate.",
        ResourceUnit.BYTES,
        ResourceAggregation.PEAK,
    )
    MATERIALIZED_STREAM_BYTES = ResourceDefinition(
        "materialized_stream_bytes",
        64 * _MIB,
        "Bytes in one materialized stream.",
        ResourceUnit.BYTES,
        ResourceAggregation.PEAK,
    )
    EXTENSIONS = ResourceDefinition(
        "extensions",
        4_096,
        "Extension declarations in one manifest.",
        ResourceUnit.COUNT,
        ResourceAggregation.PEAK,
    )
    RECIPES = ResourceDefinition(
        "recipes",
        4_096,
        "Recipes in one manifest.",
        ResourceUnit.COUNT,
        ResourceAggregation.PEAK,
    )
    STREAMS = ResourceDefinition(
        "streams",
        65_536,
        "Streams in one manifest.",
        ResourceUnit.COUNT,
        ResourceAggregation.PEAK,
    )
    TOTAL_STAGES = ResourceDefinition(
        "total_stages",
        65_536,
        "Stages across all recipes in one manifest.",
        ResourceUnit.COUNT,
        ResourceAggregation.PEAK,
    )
    STAGES_PER_RECIPE = ResourceDefinition(
        "stages_per_recipe",
        64,
        "Stages in one recipe.",
        ResourceUnit.COUNT,
        ResourceAggregation.PEAK,
    )
    CONTAINER_BYTES = ResourceDefinition(
        "container_bytes",
        16 * _GIB,
        "Bytes in one complete container.",
        ResourceUnit.BYTES,
        ResourceAggregation.TOTAL,
    )
    CHUNKS = ResourceDefinition(
        "chunks",
        262_144,
        "Chunks in one container.",
        ResourceUnit.COUNT,
        ResourceAggregation.TOTAL,
    )
    LOGICAL_BYTES = ResourceDefinition(
        "logical_bytes",
        16 * _GIB,
        "Logical bytes processed by one operation.",
        ResourceUnit.BYTES,
        ResourceAggregation.TOTAL,
    )
    STAGE_EXECUTIONS = ResourceDefinition(
        "stage_executions",
        1_048_576,
        "Stage executions in one operation.",
        ResourceUnit.COUNT,
        ResourceAggregation.TOTAL,
    )


DEFAULT_RESOURCE_POLICY: Final = ResourcePolicy(tuple(CoreResource))
DEFAULT_RESOURCE_CATALOG: Final = ResourceCatalog(
    tuple(CoreResource),
    (DEFAULT_LIMIT_PROFILE,),
)


class ResourceLimitError(ObstError):
    """A valid operation was refused by its local resource policy."""

    def __init__(
        self,
        *,
        resource: ResourceKind,
        scope: str,
        maximum: int,
        observed: int,
        phase: str,
    ) -> None:
        if not isinstance(cast(object, resource), ResourceKind):
            raise TypeError("resource must be a ResourceKind member")
        self.resource = resource
        self.scope = scope
        self.maximum = maximum
        self.observed = observed
        self.phase = phase
        super().__init__(
            f"{phase} refused {scope} {resource}: "
            f"observed {observed}, maximum {maximum}"
        )


class ResourceAccounting:
    """Aggregate and enforce typed resource observations for one operation."""

    __slots__ = ("_policy", "_values")

    def __init__(self, policy: ResourcePolicy) -> None:
        if type(policy) is not ResourcePolicy:
            raise TypeError("resource accounting policy must be a ResourcePolicy")
        self._policy = policy
        self._values = {resource: 0 for resource in policy.resources}

    def maximum(self, resource: ResourceKind, /) -> int | None:
        """Return the selected ceiling for one resource."""
        return self._policy.maximum(resource)

    def current(self, resource: ResourceKind, /) -> int:
        """Return the operation-local total or peak recorded for one resource."""
        self.maximum(resource)
        return self._values[resource]

    def check(
        self,
        resource: ResourceKind,
        observed: int,
        *,
        scope: str,
        phase: str,
    ) -> int:
        """Validate one absolute observation without changing accounting state."""
        checked_scope = _require_context("scope", scope)
        checked_phase = _require_context("phase", phase)
        checked_observed = _require_observation(observed)
        maximum = self.maximum(resource)
        if maximum is not None and checked_observed > maximum:
            raise ResourceLimitError(
                resource=resource,
                scope=checked_scope,
                maximum=maximum,
                observed=checked_observed,
                phase=checked_phase,
            )
        return checked_observed

    def record(
        self,
        resource: ResourceKind,
        amount: int,
        *,
        scope: str,
        phase: str,
    ) -> int:
        """Validate and commit one total increment or peak observation."""
        observed = self._project(resource, amount)
        self.check(
            resource,
            observed,
            scope=scope,
            phase=phase,
        )
        self._values[resource] = observed
        return observed

    def _project(self, resource: ResourceKind, amount: int) -> int:
        current = self.current(resource)
        checked_amount = _require_observation(amount)
        if resource.aggregation is ResourceAggregation.TOTAL:
            return current + checked_amount
        return max(current, checked_amount)


def _require_context(name: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"resource {name} must be an exact string")
    if not value:
        raise ValueError(f"resource {name} cannot be empty")
    return value


def _require_observation(value: object) -> int:
    if type(value) is not int:
        raise TypeError("resource observation must be an exact integer")
    if value < 0:
        raise ValueError("resource observation must be non-negative")
    return value
