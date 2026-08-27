"""Public resource limits and core-owned operation accounting."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Final

from obst.core.errors import ResourceLimitError

__all__ = ["DEFAULT_RESOURCE_LIMITS", "ResourceLimits"]

_MIB = 1024 * 1024
_GIB = 1024 * _MIB


def _require_optional_limit(name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceLimits:
    """Local ceilings for one OBST operation.

    ``None`` disables only the corresponding local ceiling. Wire
    representability and structural validity remain unconditional.
    """

    max_manifest_bytes: int | None = 16 * _MIB
    max_encoded_chunk_bytes: int | None = 64 * _MIB
    max_logical_chunk_bytes: int | None = 64 * _MIB
    max_intermediate_bytes: int | None = 64 * _MIB
    max_materialized_stream_bytes: int | None = 64 * _MIB
    max_extensions: int | None = 4_096
    max_recipes: int | None = 4_096
    max_streams: int | None = 65_536
    max_total_stages: int | None = 65_536
    max_stages_per_recipe: int | None = 64
    max_container_bytes: int | None = 16 * _GIB
    max_chunks: int | None = 262_144
    max_total_logical_bytes: int | None = 16 * _GIB
    max_stage_executions: int | None = 1_048_576

    def __post_init__(self) -> None:
        for field in fields(self):
            _require_optional_limit(field.name, getattr(self, field.name))


DEFAULT_RESOURCE_LIMITS: Final = ResourceLimits()


@dataclass(slots=True)
class ResourceBudget:
    """Monotone resource accounting shared within one core operation."""

    limits: ResourceLimits = DEFAULT_RESOURCE_LIMITS
    container_bytes: int = 0
    chunks: int = 0
    logical_bytes: int = 0
    stage_executions: int = 0

    def require(
        self,
        *,
        resource: str,
        scope: str,
        maximum: int | None,
        observed: int,
        phase: str,
    ) -> None:
        """Refuse one observed value above its configured local ceiling."""
        if maximum is not None and observed > maximum:
            raise ResourceLimitError(
                resource=resource,
                scope=scope,
                maximum=maximum,
                observed=observed,
                phase=phase,
            )

    def consume_container_bytes(self, amount: int, *, phase: str) -> None:
        self.container_bytes = self._consume(
            current=self.container_bytes,
            amount=amount,
            resource="container_bytes",
            scope="container",
            maximum=self.limits.max_container_bytes,
            phase=phase,
        )

    def consume_chunk(self, *, phase: str) -> None:
        self.chunks = self._consume(
            current=self.chunks,
            amount=1,
            resource="chunks",
            scope="container",
            maximum=self.limits.max_chunks,
            phase=phase,
        )

    def consume_logical_bytes(
        self,
        amount: int,
        *,
        scope: str,
        phase: str,
    ) -> None:
        self.logical_bytes = self._consume(
            current=self.logical_bytes,
            amount=amount,
            resource="logical_bytes",
            scope=scope,
            maximum=self.limits.max_total_logical_bytes,
            phase=phase,
        )

    def observe_logical_bytes(
        self,
        observed: int,
        *,
        scope: str,
        phase: str,
    ) -> None:
        """Advance cumulative logical-byte accounting to one observed total."""
        if type(observed) is not int or observed < self.logical_bytes:
            raise ValueError(
                "observed logical bytes must be a monotone non-negative integer"
            )
        self.require(
            resource="logical_bytes",
            scope=scope,
            maximum=self.limits.max_total_logical_bytes,
            observed=observed,
            phase=phase,
        )
        self.logical_bytes = observed

    def consume_stage_execution(self, *, scope: str, phase: str) -> None:
        self.stage_executions = self._consume(
            current=self.stage_executions,
            amount=1,
            resource="stage_executions",
            scope=scope,
            maximum=self.limits.max_stage_executions,
            phase=phase,
        )

    def _consume(
        self,
        *,
        current: int,
        amount: int,
        resource: str,
        scope: str,
        maximum: int | None,
        phase: str,
    ) -> int:
        if type(amount) is not int or amount < 0:
            raise ValueError("resource consumption must be a non-negative integer")
        observed = current + amount
        self.require(
            resource=resource,
            scope=scope,
            maximum=maximum,
            observed=observed,
            phase=phase,
        )
        return observed
