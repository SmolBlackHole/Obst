"""Generic execution of immutable plugin-owned conformance suites."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import cast

from obst.conformance.model import (
    ConformanceCaseResult,
    ConformanceReport,
    ConformanceSuite,
    ContainerRecoveryCase,
    ContainerStructuralOutcome,
    ContainerStructureCase,
    PortableConformanceCase,
    StageBindRejectionCase,
    StageDecodeRejectionCase,
    StageKnownAnswerCase,
    StageOutputLimitCase,
    StageParametersCase,
    StreamMetadataCase,
    StreamMetadataRejectionCase,
    case_extension_id,
)
from obst.core.container import ContainerReader
from obst.core.errors import (
    CorruptContainerError,
    InvalidContainerError,
    ObstError,
    ProviderRejectedError,
    TruncatedContainerError,
    UnsupportedVersionError,
)
from obst.core.extensions import (
    Extension,
    StageParameterEncoder,
    StreamMetadataEncoder,
    provider_rejection_resource_limit,
)
from obst.core.inspection import inspect_container
from obst.core.model import Recipe, StageSpec
from obst.core.pipeline import RecipeDecoder, RecipeEncoder
from obst.core.registry import (
    ExtensionCapability,
    ExtensionRegistry,
    StageCapability,
    StreamProfileCapability,
)
from obst.core.resource_accounting import (
    DEFAULT_RESOURCE_POLICY,
    ResourceAccounting,
)
from obst.core.streams import materialize_stream


class ConformanceError(ObstError):
    """A portable suite or its claimed coverage violates the contract."""


def run_conformance_suite(
    suite: ConformanceSuite,
    extensions: tuple[Extension, ...] = (),
    *,
    dependencies: tuple[Extension, ...] = (),
) -> ConformanceReport:
    """Run one static suite against explicit owned and dependency Extensions."""
    if type(suite) is not ConformanceSuite:
        raise TypeError("suite must be an exact ConformanceSuite")
    if type(extensions) is not tuple:
        raise TypeError("extensions must be a tuple")
    if type(dependencies) is not tuple:
        raise TypeError("dependencies must be a tuple")
    try:
        owned_registry = ExtensionRegistry(extensions)
        registry = ExtensionRegistry((*extensions, *dependencies))
    except Exception as exc:
        raise ConformanceError(
            f"cannot compose conformance registry: {type(exc).__name__}: {exc}"
        ) from exc
    _validate_suite_coverage(suite, owned_registry.capabilities(), registry)
    results: list[ConformanceCaseResult] = []
    for case in suite.cases:
        try:
            _check_case(
                registry,
                case,
                accounting=ResourceAccounting(DEFAULT_RESOURCE_POLICY),
            )
        except Exception as exc:
            results.append(
                ConformanceCaseResult(
                    case.case_id,
                    case_extension_id(case),
                    case.kind,
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            results.append(
                ConformanceCaseResult(
                    case.case_id,
                    case_extension_id(case),
                    case.kind,
                    True,
                    None,
                )
            )
    return ConformanceReport(tuple(results))


def _validate_suite_coverage(
    suite: ConformanceSuite,
    owned: tuple[ExtensionCapability, ...],
    registry: ExtensionRegistry,
) -> None:
    owned_ids = {capability.extension_id for capability in owned}
    known_ids = {capability.extension_id for capability in registry.capabilities()}
    for case in suite.cases:
        extension_id = case_extension_id(case)
        if extension_id is not None and extension_id not in owned_ids:
            raise ConformanceError(
                f"case {case.case_id} targets {extension_id}, which the plugin does not provide"
            )
        if type(case) is ContainerRecoveryCase:
            missing = set(case.required_extensions) - known_ids
            if missing:
                raise ConformanceError(
                    f"case {case.case_id} requires unavailable extensions: "
                    f"{', '.join(sorted(missing))}"
                )
    for capability in owned:
        if type(capability) is StageCapability:
            _require_stage_coverage(suite, capability)
        elif type(capability) is StreamProfileCapability:
            _require_stream_profile_coverage(suite, capability)


def _require_stage_coverage(
    suite: ConformanceSuite,
    capability: StageCapability,
) -> None:
    stage_cases = tuple(
        case
        for case in suite.cases
        if case_extension_id(case) == capability.extension_id
    )
    if (capability.encoder_available or capability.decoder_available) and not any(
        type(case) is StageKnownAnswerCase for case in stage_cases
    ):
        raise ConformanceError(
            f"suite does not cover Stage bytes for {capability.extension_id}"
        )
    parameter_capability = (
        capability.parameter_encoder_available
        or capability.parameter_decoder_available
        or capability.parameter_interpreter_available
    )
    if parameter_capability and not any(
        type(case) is StageParametersCase for case in stage_cases
    ):
        raise ConformanceError(
            f"suite does not cover Stage parameters for {capability.extension_id}"
        )


def _require_stream_profile_coverage(
    suite: ConformanceSuite,
    capability: StreamProfileCapability,
) -> None:
    metadata_capability = (
        capability.metadata_encoder_available
        or capability.metadata_decoder_available
        or capability.metadata_interpreter_available
    )
    if metadata_capability and not any(
        type(case) is StreamMetadataCase
        and case.extension_id == capability.extension_id
        for case in suite.cases
    ):
        raise ConformanceError(
            f"suite does not cover stream metadata for {capability.extension_id}"
        )


def _check_case(
    registry: ExtensionRegistry,
    case: PortableConformanceCase,
    *,
    accounting: ResourceAccounting,
) -> None:
    if type(case) is StageKnownAnswerCase:
        _check_stage_known_answer(registry, case, accounting=accounting)
    elif type(case) is StageParametersCase:
        _check_stage_parameters(registry, case)
    elif type(case) is StageBindRejectionCase:
        _check_stage_bind_rejection(registry, case)
    elif type(case) is StageDecodeRejectionCase:
        _check_stage_decode_rejection(registry, case)
    elif type(case) is StageOutputLimitCase:
        _check_stage_output_limit(registry, case)
    elif type(case) is StreamMetadataCase:
        _check_stream_metadata(registry, case)
    elif type(case) is StreamMetadataRejectionCase:
        _check_stream_metadata_rejection(registry, case)
    elif type(case) is ContainerStructureCase:
        _check_container_structure(case, accounting=accounting)
    else:
        assert type(case) is ContainerRecoveryCase
        _check_container_recovery(registry, case, accounting=accounting)


def _check_stage_known_answer(
    registry: ExtensionRegistry,
    case: StageKnownAnswerCase,
    *,
    accounting: ResourceAccounting,
) -> None:
    recipe = Recipe(0, (StageSpec(case.extension_id, case.parameters),))
    can_encode = registry.can_encode(case.extension_id)
    can_decode = registry.can_decode(case.extension_id)
    if not can_encode and not can_decode:
        raise ConformanceError("Stage provides neither encoder nor decoder")
    if can_decode:
        decoded = RecipeDecoder(registry, accounting=accounting).decode(
            case.encoded,
            recipe,
            expected_size=len(case.logical),
        )
        if decoded != case.logical:
            raise ConformanceError("known encoding did not recover expected bytes")
    if can_encode:
        encoded = RecipeEncoder(registry, accounting=accounting).encode(
            case.logical, recipe
        )
        if case.canonical_encoding and encoded != case.encoded:
            raise ConformanceError("encoder did not reproduce canonical encoding")
        if can_decode:
            decoded = RecipeDecoder(registry, accounting=accounting).decode(
                encoded,
                recipe,
                expected_size=len(case.logical),
            )
            if decoded != case.logical:
                raise ConformanceError("locally encoded bytes did not round-trip")
        elif not case.canonical_encoding:
            raise ConformanceError(
                "encoder-only known-answer case must require canonical encoding"
            )


def _check_stage_parameters(
    registry: ExtensionRegistry,
    case: StageParametersCase,
) -> None:
    decoder = registry.get_stage_parameter_decoder(case.extension_id)
    encoder = registry.get_stage_parameter_encoder(case.extension_id)
    interpreter = registry.get_stage_parameter_interpreter(case.extension_id)
    if decoder is None:
        raise ConformanceError("Stage parameter decoder is unavailable")
    value = decoder.decode_parameters(case.parameters)
    typed_encoder = cast(StageParameterEncoder[object] | None, encoder)
    if (
        typed_encoder is not None
        and typed_encoder.encode_parameters(value) != case.parameters
    ):
        raise ConformanceError("Stage parameter encoding is not canonical")
    if case.interpretation is not None:
        if interpreter is None:
            raise ConformanceError("Stage parameter interpreter is unavailable")
        if interpreter.interpret_parameters(case.parameters) != case.interpretation:
            raise ConformanceError("Stage parameter interpretation differs")


def _check_stage_bind_rejection(
    registry: ExtensionRegistry,
    case: StageBindRejectionCase,
) -> None:
    parameter_decoder = registry.get_stage_parameter_decoder(case.extension_id)
    if parameter_decoder is not None:
        _require_provider_rejection(
            lambda: parameter_decoder.decode_parameters(case.parameters),
            "parameter decoder accepted rejected parameters",
        )
    interpreter = registry.get_stage_parameter_interpreter(case.extension_id)
    if interpreter is not None:
        interpretation = interpreter.interpret_parameters(case.parameters)
        if interpretation.error is None:
            raise ConformanceError("parameter interpreter did not report an error")
    if "encode" in case.directions:
        encoder_provider = registry.require_encoder_provider(case.extension_id)
        _require_provider_rejection(
            lambda: encoder_provider.bind_encoder(case.parameters),
            "encoder accepted rejected parameters",
        )
    if "decode" in case.directions:
        decoder_provider = registry.require_decoder_provider(case.extension_id)
        _require_provider_rejection(
            lambda: decoder_provider.bind_decoder(case.parameters),
            "decoder accepted rejected parameters",
        )


def _check_stage_decode_rejection(
    registry: ExtensionRegistry,
    case: StageDecodeRejectionCase,
) -> None:
    provider = registry.require_decoder_provider(case.extension_id)
    bound = provider.bind_decoder(case.parameters)
    _require_provider_rejection(
        lambda: bound.decode(
            case.encoded,
            max_output_size=case.max_output_size,
        ),
        "decoder accepted rejected payload",
    )


def _check_stage_output_limit(
    registry: ExtensionRegistry,
    case: StageOutputLimitCase,
) -> None:
    if case.direction == "encode":
        bound_encoder = registry.require_encoder_provider(
            case.extension_id
        ).bind_encoder(case.parameters)
        _require_output_limit(
            lambda maximum: bound_encoder.encode(
                case.data,
                max_output_size=maximum,
            ),
            case.max_output_size,
            "encoder",
        )
        return
    bound_decoder = registry.require_decoder_provider(case.extension_id).bind_decoder(
        case.parameters
    )
    _require_output_limit(
        lambda maximum: bound_decoder.decode(
            case.data,
            max_output_size=maximum,
        ),
        case.max_output_size,
        "decoder",
    )


def _check_stream_metadata(
    registry: ExtensionRegistry,
    case: StreamMetadataCase,
) -> None:
    decoder = registry.get_stream_metadata_decoder(case.extension_id)
    encoder = registry.get_stream_metadata_encoder(case.extension_id)
    interpreter = registry.get_stream_metadata_interpreter(case.extension_id)
    if decoder is None:
        raise ConformanceError("stream metadata decoder is unavailable")
    value = decoder.decode_metadata(case.metadata)
    typed_encoder = cast(StreamMetadataEncoder[object] | None, encoder)
    if (
        typed_encoder is not None
        and typed_encoder.encode_metadata(value) != case.metadata
    ):
        raise ConformanceError("stream metadata encoding is not canonical")
    if case.interpretation is not None:
        if interpreter is None:
            raise ConformanceError("stream metadata interpreter is unavailable")
        if interpreter.interpret_metadata(case.metadata) != case.interpretation:
            raise ConformanceError("stream metadata interpretation differs")


def _check_stream_metadata_rejection(
    registry: ExtensionRegistry,
    case: StreamMetadataRejectionCase,
) -> None:
    decoder = registry.get_stream_metadata_decoder(case.extension_id)
    if decoder is None:
        raise ConformanceError("stream metadata decoder is unavailable")
    _require_provider_rejection(
        lambda: decoder.decode_metadata(case.metadata),
        "stream metadata decoder accepted rejected metadata",
    )
    if case.require_interpreter_error:
        interpreter = registry.get_stream_metadata_interpreter(case.extension_id)
        if interpreter is None:
            raise ConformanceError("stream metadata interpreter is unavailable")
        if interpreter.interpret_metadata(case.metadata).error is None:
            raise ConformanceError(
                "stream metadata interpreter did not report an error"
            )


def _check_container_recovery(
    registry: ExtensionRegistry,
    case: ContainerRecoveryCase,
    *,
    accounting: ResourceAccounting,
) -> None:
    for stream in case.streams:
        logical = materialize_stream(
            ContainerReader(io.BytesIO(case.container), accounting=accounting),
            stream.stream_id,
            registry,
        )
        if logical != stream.logical:
            raise ConformanceError(
                f"container stream {stream.stream_id} did not recover expected bytes"
            )


_STRUCTURAL_OUTCOMES: dict[type[InvalidContainerError], ContainerStructuralOutcome] = {
    InvalidContainerError: ContainerStructuralOutcome.INVALID_STRUCTURE,
    CorruptContainerError: ContainerStructuralOutcome.CORRUPT,
    TruncatedContainerError: ContainerStructuralOutcome.TRUNCATED,
    UnsupportedVersionError: ContainerStructuralOutcome.UNSUPPORTED_VERSION,
}


def _check_container_structure(
    case: ContainerStructureCase,
    *,
    accounting: ResourceAccounting,
) -> None:
    try:
        inspection = inspect_container(
            ContainerReader(io.BytesIO(case.container), accounting=accounting)
        )
    except InvalidContainerError as exc:
        if case.outcome is ContainerStructuralOutcome.ACCEPT:
            raise ConformanceError(
                f"container was rejected as {type(exc).__name__}: {exc}"
            ) from exc
        try:
            actual = _STRUCTURAL_OUTCOMES[type(exc)]
        except KeyError as classification_error:
            raise ConformanceError(
                f"unclassified structural rejection {type(exc).__name__}: {exc}"
            ) from classification_error
        if actual is not case.outcome:
            raise ConformanceError(
                f"container rejection was {actual.value}, expected {case.outcome.value}"
            ) from exc
        return
    if case.outcome is not ContainerStructuralOutcome.ACCEPT:
        raise ConformanceError(f"container was accepted, expected {case.outcome.value}")
    if inspection.missing_required_stages != case.missing_required_stages:
        raise ConformanceError(
            "missing required Stages differ: "
            f"got {inspection.missing_required_stages}, "
            f"expected {case.missing_required_stages}"
        )


def _require_provider_rejection(
    operation: Callable[[], object],
    message: str,
) -> None:
    try:
        operation()
    except ProviderRejectedError as rejection:
        if type(rejection) is not ProviderRejectedError:
            raise ConformanceError(
                "provider used a specialized rejection for an invalid-input case"
            ) from rejection
        return
    except Exception as exc:
        raise ConformanceError(
            f"provider crashed instead of rejecting input: {type(exc).__name__}: {exc}"
        ) from exc
    raise ConformanceError(message)


def _require_output_limit(
    operation: Callable[[int | None], bytes],
    maximum: int,
    direction: str,
) -> None:
    try:
        unbounded = operation(None)
    except Exception as exc:
        raise ConformanceError(
            f"{direction} failed without an output ceiling: {type(exc).__name__}: {exc}"
        ) from exc
    if len(unbounded) <= maximum:
        raise ConformanceError(
            f"{direction} output has {len(unbounded)} bytes and does not exceed "
            f"the test ceiling {maximum}"
        )
    try:
        operation(maximum)
    except ProviderRejectedError as rejection:
        resource_limit = provider_rejection_resource_limit(rejection)
        if resource_limit is None:
            raise ConformanceError(
                f"{direction} rejected the input without a structured output limit"
            ) from rejection
        if resource_limit.maximum != maximum:
            raise ConformanceError(
                f"{direction} reported maximum {resource_limit.maximum}, "
                f"expected {maximum}"
            ) from rejection
        if resource_limit.observed <= maximum:
            raise ConformanceError(
                f"{direction} reported non-exceeding output size "
                f"{resource_limit.observed}"
            ) from rejection
        return
    except Exception as exc:
        raise ConformanceError(
            f"{direction} crashed under its output ceiling: {type(exc).__name__}: {exc}"
        ) from exc
    raise ConformanceError(f"{direction} exceeded the declared output limit")


__all__ = [
    "ConformanceError",
    "run_conformance_suite",
]
