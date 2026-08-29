from __future__ import annotations

import pytest

from obst.core import (
    CoreResource,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionRegistry,
    PipelineError,
    ProviderRejectedError,
    Recipe,
    ResourceLimitError,
    StageSpec,
    decode_recipe,
    encode_recipe,
    extend_stage_output,
    require_stage_output_size,
)
from obst.core.extensions import ExtensionKind
from tests.support_extensions import (
    CompressionExtension,
    CompressionParameters,
    DeltaExtension,
    IdentityExtension,
)
from tests.support_resources import policy as _policy

_EXPLODING_ID = "org.example/exploding@1"
_REJECTING_ID = "org.example/rejecting@1"
_INVALID_OUTPUT_ID = "org.example/invalid-output@1"


def test_public_stage_output_helpers_enforce_before_accumulation() -> None:
    output = bytearray(b"ab")

    extend_stage_output(
        output,
        b"cd",
        stage_id=IdentityExtension.extension_id,
        max_output_size=4,
        operation="encode",
    )
    assert output == b"abcd"

    with pytest.raises(ProviderRejectedError) as rejection:
        extend_stage_output(
            output,
            b"e",
            stage_id=IdentityExtension.extension_id,
            max_output_size=4,
            operation="encode",
        )

    assert output == b"abcd"
    assert rejection.value.resource_limit is not None
    assert rejection.value.resource_limit.maximum == 4
    assert rejection.value.resource_limit.observed == 5


def test_public_stage_output_size_helper_accepts_disabled_ceiling() -> None:
    require_stage_output_size(
        IdentityExtension.extension_id,
        1_000_000,
        max_output_size=None,
        operation="decode",
    )


def test_recipe_execution_is_reversible_across_multiple_neutral_stages() -> None:
    compression = CompressionExtension()
    recipe = Recipe(
        0,
        (
            StageSpec(DeltaExtension.extension_id),
            StageSpec(
                CompressionExtension.extension_id,
                compression.encode_parameters(CompressionParameters(6)),
            ),
        ),
    )
    registry = ExtensionRegistry((DeltaExtension(), compression))
    logical = bytes(range(128)) * 4

    encoded = encode_recipe(logical, recipe, registry)

    assert encoded != logical
    assert (
        decode_recipe(encoded, recipe, registry, expected_size=len(logical)) == logical
    )


def test_recipe_execution_enforces_intermediate_output_limits() -> None:
    recipe = Recipe(0, (StageSpec(IdentityExtension.extension_id),))
    registry = ExtensionRegistry((IdentityExtension(),))

    with pytest.raises(ResourceLimitError) as caught:
        encode_recipe(
            b"payload",
            recipe,
            registry,
            policy=_policy((CoreResource.INTERMEDIATE_BYTES, 6)),
        )

    assert caught.value.resource is CoreResource.INTERMEDIATE_BYTES
    assert caught.value.maximum == 6
    assert caught.value.observed == 7


class _ExplodingStage:
    extension_id = _EXPLODING_ID
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def bind_encoder(self, parameters: bytes, /) -> _ExplodingStage:
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        raise RuntimeError("implementation crashed")


def test_unexpected_provider_exceptions_have_stable_extension_context() -> None:
    recipe = Recipe(0, (StageSpec(_EXPLODING_ID),))

    with pytest.raises(ExtensionContractError) as caught:
        encode_recipe(
            b"payload",
            recipe,
            ExtensionRegistry((_ExplodingStage(),)),
        )

    assert caught.value.extension_id == _EXPLODING_ID
    assert caught.value.capability == "encode execute"
    assert "RuntimeError: implementation crashed" in caught.value.reason


class _RejectingStage:
    extension_id = _REJECTING_ID
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def bind_decoder(self, parameters: bytes, /) -> _RejectingStage:
        return self

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        raise ProviderRejectedError("payload rejected")


def test_expected_provider_rejection_becomes_structured_pipeline_error() -> None:
    recipe = Recipe(0, (StageSpec(_REJECTING_ID),))

    with pytest.raises(PipelineError) as caught:
        decode_recipe(
            b"payload",
            recipe,
            ExtensionRegistry((_RejectingStage(),)),
            expected_size=7,
        )

    assert caught.value.stage_id == _REJECTING_ID
    assert caught.value.direction == "decode"
    assert caught.value.phase == "execute"
    assert caught.value.reason == "payload rejected"


class _InvalidOutputStage:
    extension_id = _INVALID_OUTPUT_ID
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def bind_encoder(self, parameters: bytes, /) -> _InvalidOutputStage:
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return bytearray(data)  # type: ignore[return-value]


def test_executor_rejects_provider_outputs_that_violate_the_protocol() -> None:
    recipe = Recipe(0, (StageSpec(_INVALID_OUTPUT_ID),))

    with pytest.raises(ExtensionContractError, match="return bytes"):
        encode_recipe(
            b"payload",
            recipe,
            ExtensionRegistry((_InvalidOutputStage(),)),
        )
