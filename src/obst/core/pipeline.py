"""Core forward and reverse execution of registered stage recipes."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, cast

from obst.core.errors import (
    ExtensionContractError,
    PipelineError,
    ProviderRejectedError,
)
from obst.core.extensions import (
    StageDecoderProvider,
    StageEncoderProvider,
    provider_rejection_resource_limit,
)
from obst.core.model import Recipe, StageSpec
from obst.core.registry import ExtensionRegistry
from obst.core.resource_accounting import (
    CoreResource,
    ResourceAccounting,
)

type _Direction = Literal["encode", "decode"]
type _Phase = Literal["bind", "execute"]


@dataclass(frozen=True, slots=True)
class _EncoderBinding:
    stage_id: str
    operation: Callable[..., bytes]


@dataclass(frozen=True, slots=True)
class _DecoderBinding:
    stage_id: str
    operation: Callable[..., bytes]


@dataclass(frozen=True, slots=True)
class _ResolvedEncoderStage:
    spec: StageSpec
    provider: StageEncoderProvider


@dataclass(frozen=True, slots=True)
class _ResolvedDecoderStage:
    spec: StageSpec
    provider: StageDecoderProvider


class RecipeEncoder:
    """Bind and execute recipes within one cumulative forward operation."""

    __slots__ = ("_accounting", "_bindings", "_registry")

    def __init__(
        self,
        registry: ExtensionRegistry,
        *,
        accounting: ResourceAccounting,
    ) -> None:
        if type(accounting) is not ResourceAccounting:
            raise TypeError("recipe encoder accounting must be ResourceAccounting")
        self._bindings: dict[Recipe, tuple[_EncoderBinding, ...]] = {}
        self._accounting = accounting
        self._registry = registry

    def preflight(self, recipes: Iterable[Recipe], /) -> None:
        """Resolve then bind every not-yet-cached recipe before publication."""
        pending: list[Recipe] = []
        seen = set(self._bindings)
        for recipe in recipes:
            if recipe not in seen:
                pending.append(recipe)
                seen.add(recipe)
        resolved = tuple(
            (recipe, _resolve_encoder_recipe(recipe, self._registry))
            for recipe in pending
        )
        for recipe, provider_specs in resolved:
            self._bindings[recipe] = _bind_resolved_encoder_recipe(provider_specs)

    def encode(
        self,
        data: bytes,
        recipe: Recipe,
        /,
        *,
        max_output_size: int | None = None,
    ) -> bytes:
        """Encode one bounded logical chunk using a cached recipe binding."""
        _require_exact_bytes("recipe input", data)
        _require_optional_output_size(max_output_size)
        _precheck_recipe_operation(
            self._accounting,
            input_size=len(data),
            logical_size=len(data),
            stage_count=len(recipe.stages),
            direction="encode",
        )
        bindings = self._bindings.get(recipe)
        if bindings is None:
            self.preflight((recipe,))
            bindings = self._bindings[recipe]
        return _execute_encoder_recipe(
            data,
            bindings,
            self._accounting,
            max_output_size=max_output_size,
        )


class RecipeDecoder:
    """Bind and execute only required recipes within one reverse operation."""

    __slots__ = ("_accounting", "_bindings", "_registry")

    def __init__(
        self,
        registry: ExtensionRegistry,
        *,
        accounting: ResourceAccounting,
    ) -> None:
        if type(accounting) is not ResourceAccounting:
            raise TypeError("recipe decoder accounting must be ResourceAccounting")
        self._bindings: dict[Recipe, tuple[_DecoderBinding, ...]] = {}
        self._accounting = accounting
        self._registry = registry

    def decode(
        self,
        data: bytes,
        recipe: Recipe,
        /,
        *,
        expected_size: int,
    ) -> bytes:
        """Decode one bounded payload after lazy recipe binding."""
        _require_exact_bytes("recipe input", data)
        _require_expected_size(expected_size)
        _precheck_recipe_operation(
            self._accounting,
            input_size=len(data),
            logical_size=expected_size,
            stage_count=len(recipe.stages),
            direction="decode",
        )
        bindings = self._bindings.get(recipe)
        if bindings is None:
            bindings = _bind_decoder_recipe(recipe, self._registry)
            self._bindings[recipe] = bindings
        return _execute_decoder_recipe(
            data,
            bindings,
            expected_size=expected_size,
            accounting=self._accounting,
        )


def _execute_encoder_recipe(
    data: bytes,
    bindings: tuple[_EncoderBinding, ...],
    accounting: ResourceAccounting,
    *,
    max_output_size: int | None,
) -> bytes:
    _require_exact_bytes("recipe input", data)
    accounting.record(
        CoreResource.LOGICAL_BYTES,
        len(data),
        scope="recipe input",
        phase="recipe_encode",
    )
    _require_intermediate_bytes(
        accounting,
        len(data),
        scope="recipe input",
        phase="recipe_encode",
    )
    result = data
    for index, binding in enumerate(bindings):
        stage_output_size = accounting.maximum(CoreResource.INTERMEDIATE_BYTES)
        if index == len(bindings) - 1:
            stage_output_size = _minimum_output_size(
                stage_output_size,
                max_output_size,
            )
        accounting.record(
            CoreResource.STAGE_EXECUTIONS,
            1,
            scope=binding.stage_id,
            phase="recipe_encode",
        )
        result = _invoke_stage_operation(
            binding.stage_id,
            "encode",
            binding.operation,
            result,
            max_output_size=stage_output_size,
        )
        _validate_provider_output(
            result,
            stage_id=binding.stage_id,
            direction="encode",
            max_output_size=stage_output_size,
        )
    return result


def _execute_decoder_recipe(
    data: bytes,
    bindings: tuple[_DecoderBinding, ...],
    *,
    expected_size: int,
    accounting: ResourceAccounting,
) -> bytes:
    _require_exact_bytes("recipe input", data)
    accounting.record(
        CoreResource.LOGICAL_BYTES,
        expected_size,
        scope="recipe output",
        phase="recipe_decode",
    )
    _require_intermediate_bytes(
        accounting,
        len(data),
        scope="recipe input",
        phase="recipe_decode",
    )
    result = data
    for index, binding in enumerate(bindings):
        stage_output_size = accounting.maximum(CoreResource.INTERMEDIATE_BYTES)
        if index == len(bindings) - 1:
            stage_output_size = _minimum_output_size(
                stage_output_size,
                expected_size,
            )
        accounting.record(
            CoreResource.STAGE_EXECUTIONS,
            1,
            scope=binding.stage_id,
            phase="recipe_decode",
        )
        result = _invoke_stage_operation(
            binding.stage_id,
            "decode",
            binding.operation,
            result,
            max_output_size=stage_output_size,
        )
        _validate_provider_output(
            result,
            stage_id=binding.stage_id,
            direction="decode",
            max_output_size=stage_output_size,
        )
    if len(result) != expected_size:
        raise PipelineError(
            f"decoded size mismatch: expected {expected_size}, got {len(result)}"
        )
    return result


def encode_recipe(
    data: bytes,
    recipe: Recipe,
    registry: ExtensionRegistry,
    *,
    accounting: ResourceAccounting,
) -> bytes:
    """Bind and execute one recipe as one bounded forward operation."""
    _require_exact_bytes("recipe input", data)
    return RecipeEncoder(registry, accounting=accounting).encode(data, recipe)


def decode_recipe(
    data: bytes,
    recipe: Recipe,
    registry: ExtensionRegistry,
    *,
    expected_size: int,
    accounting: ResourceAccounting,
) -> bytes:
    """Bind and execute one recipe as one bounded reverse operation."""
    _require_exact_bytes("recipe input", data)
    return RecipeDecoder(registry, accounting=accounting).decode(
        data,
        recipe,
        expected_size=expected_size,
    )


def _resolve_encoder_recipe(
    recipe: Recipe,
    registry: ExtensionRegistry,
) -> tuple[_ResolvedEncoderStage, ...]:
    return tuple(
        _ResolvedEncoderStage(
            stage_spec,
            registry.require_encoder_provider(stage_spec.stage_id),
        )
        for stage_spec in recipe.stages
    )


def _bind_resolved_encoder_recipe(
    resolved: tuple[_ResolvedEncoderStage, ...],
) -> tuple[_EncoderBinding, ...]:
    return tuple(_bind_encoder(stage.spec, stage.provider) for stage in resolved)


def _bind_decoder_recipe(
    recipe: Recipe,
    registry: ExtensionRegistry,
) -> tuple[_DecoderBinding, ...]:
    resolved = _resolve_decoder_recipe(recipe, registry)
    return tuple(_bind_decoder(stage.spec, stage.provider) for stage in resolved)


def _resolve_decoder_recipe(
    recipe: Recipe,
    registry: ExtensionRegistry,
) -> tuple[_ResolvedDecoderStage, ...]:
    return tuple(
        _ResolvedDecoderStage(
            stage_spec,
            registry.require_decoder_provider(stage_spec.stage_id),
        )
        for stage_spec in reversed(recipe.stages)
    )


def _bind_encoder(
    stage_spec: StageSpec,
    provider: StageEncoderProvider,
) -> _EncoderBinding:
    bind = _require_provider_operation(
        stage_spec.stage_id,
        "encode",
        provider,
        "bind_encoder",
    )
    result = _invoke_provider(
        stage_spec.stage_id,
        "encode",
        "bind",
        bind,
        stage_spec.parameters,
    )
    return _EncoderBinding(
        stage_spec.stage_id,
        _require_bound_operation(
            stage_spec.stage_id,
            "encode",
            result,
            "encode",
        ),
    )


def _bind_decoder(
    stage_spec: StageSpec,
    provider: StageDecoderProvider,
) -> _DecoderBinding:
    bind = _require_provider_operation(
        stage_spec.stage_id,
        "decode",
        provider,
        "bind_decoder",
    )
    result = _invoke_provider(
        stage_spec.stage_id,
        "decode",
        "bind",
        bind,
        stage_spec.parameters,
    )
    return _DecoderBinding(
        stage_spec.stage_id,
        _require_bound_operation(
            stage_spec.stage_id,
            "decode",
            result,
            "decode",
        ),
    )


def _require_provider_operation(
    stage_id: str,
    direction: _Direction,
    provider: object,
    member: str,
) -> Callable[..., object]:
    try:
        operation = getattr(provider, member)
    except Exception as exc:
        raise ExtensionContractError(
            stage_id,
            f"{direction} bind",
            f"cannot access {member}: {type(exc).__name__}: {exc}",
        ) from exc
    if not callable(operation):
        raise ExtensionContractError(
            stage_id,
            f"{direction} bind",
            f"provider {member} must be callable",
        )
    return cast(
        Callable[..., object],
        operation,
    )  # pyright: ignore[reportUnnecessaryCast]


def _require_bound_operation(
    stage_id: str,
    direction: _Direction,
    executor: object,
    member: str,
) -> Callable[..., bytes]:
    try:
        operation = getattr(executor, member)
    except Exception as exc:
        raise ExtensionContractError(
            stage_id,
            f"{direction} bind",
            f"bound executor does not expose {member}: {type(exc).__name__}: {exc}",
        ) from exc
    if not callable(operation):
        raise ExtensionContractError(
            stage_id,
            f"{direction} bind",
            f"bound executor {member} must be callable",
        )
    return cast(Callable[..., bytes], operation)


def _invoke_stage_operation(
    stage_id: str,
    direction: _Direction,
    operation: Callable[..., bytes],
    data: bytes,
    *,
    max_output_size: int | None,
) -> bytes:
    return _invoke_provider(
        stage_id,
        direction,
        "execute",
        operation,
        data,
        max_output_size=max_output_size,
    )


def _invoke_provider[T, **P](
    stage_id: str,
    direction: _Direction,
    phase: _Phase,
    operation: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    try:
        return operation(*args, **kwargs)
    except ProviderRejectedError as exc:
        if (resource_limit := provider_rejection_resource_limit(exc)) is not None:
            raise resource_limit from exc
        if type(exc) is not ProviderRejectedError:
            raise ExtensionContractError(
                stage_id,
                f"{direction} {phase}",
                "provider must raise an exact ProviderRejectedError",
            ) from exc
        if type(exc.reason) is not str or not exc.reason:
            raise ExtensionContractError(
                stage_id,
                f"{direction} {phase}",
                "provider rejection reason must be a non-empty exact string",
            ) from exc
        raise PipelineError(
            exc.reason,
            stage_id=stage_id,
            direction=direction,
            phase=phase,
        ) from exc
    except Exception as exc:
        raise ExtensionContractError(
            stage_id,
            f"{direction} {phase}",
            f"provider raised {type(exc).__name__}: {exc}",
        ) from exc


def _validate_provider_output(
    result: object,
    *,
    stage_id: str,
    direction: _Direction,
    max_output_size: int | None,
) -> None:
    if type(result) is not bytes:
        raise ExtensionContractError(
            stage_id,
            f"{direction} execute",
            "provider must return bytes",
        )
    if max_output_size is not None and len(result) > max_output_size:
        raise ExtensionContractError(
            stage_id,
            f"{direction} execute",
            f"provider returned {len(result)} bytes above its "
            f"{max_output_size}-byte output ceiling",
        )


def _require_intermediate_bytes(
    accounting: ResourceAccounting,
    observed: int,
    *,
    scope: str,
    phase: str,
) -> None:
    accounting.record(
        CoreResource.INTERMEDIATE_BYTES,
        observed,
        scope=scope,
        phase=phase,
    )


def _precheck_recipe_operation(
    accounting: ResourceAccounting,
    *,
    input_size: int,
    logical_size: int,
    stage_count: int,
    direction: _Direction,
) -> None:
    phase = f"recipe_{direction}"
    accounting.check(
        CoreResource.LOGICAL_BYTES,
        accounting.current(CoreResource.LOGICAL_BYTES) + logical_size,
        scope="recipe input" if direction == "encode" else "recipe output",
        phase=phase,
    )
    accounting.check(
        CoreResource.STAGE_EXECUTIONS,
        accounting.current(CoreResource.STAGE_EXECUTIONS) + stage_count,
        scope="recipe",
        phase=phase,
    )
    _require_intermediate_bytes(
        accounting,
        input_size,
        scope="recipe input",
        phase=phase,
    )


def _require_expected_size(expected_size: object) -> None:
    if type(expected_size) is not int:
        raise TypeError("expected_size must be an integer")
    if expected_size < 0:
        raise ValueError("expected_size must be non-negative")


def _require_optional_output_size(max_output_size: object) -> None:
    if max_output_size is None:
        return
    if type(max_output_size) is not int:
        raise TypeError("max_output_size must be an integer or None")
    if max_output_size < 0:
        raise ValueError("max_output_size must be non-negative")


def _minimum_output_size(
    first: int | None,
    second: int | None,
) -> int | None:
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


def _require_exact_bytes(name: str, value: object) -> None:
    if type(value) is not bytes:
        raise TypeError(f"{name} must be exact bytes")
