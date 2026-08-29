from __future__ import annotations

import zlib as stdlib_zlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from obst.core import (
    ChunkEncoder,
    CoreResource,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionRegistry,
    ObstError,
    PipelineError,
    ProviderRejectedError,
    Recipe,
    ResourceAccounting,
    ResourceLimitError,
    StageSpec,
    decode_recipe,
    encode_recipe,
    extend_stage_output,
    require_no_parameters,
    require_stage_output_size,
)
from obst.core.extensions import ExtensionKind

from obst_defaults.codecs.zlib import (
    ZlibDictionaryExtension,
    ZlibDictionaryParameters,
    ZlibExtension,
    ZlibParameters,
)
from obst_defaults.transforms.delta8 import Delta8Extension
from support_resources import accounting as _accounting
from support_resources import policy as _policy

DELTA8_STAGE_ID = Delta8Extension.extension_id
ZLIB_STAGE_ID = ZlibExtension.extension_id
ZLIB_DICTIONARY_STAGE_ID = ZlibDictionaryExtension.extension_id
_ZLIB = ZlibExtension()
_ZLIB_DICTIONARY = ZlibDictionaryExtension()

_XOR_ID = "org.example/xor32@1"
_XOR_DESCRIPTOR = ExtensionDescriptor(
    display_name="XOR 0x32",
    summary="XOR every byte with 0x32.",
    specification_url="https://example.org/obst/xor32-v1",
)

_FIRST_PARTY_STAGE_EXTENSIONS = (
    Delta8Extension(),
    _ZLIB,
    _ZLIB_DICTIONARY,
)
_INVALID_ZLIB_PARAMETERS = st.one_of(
    st.just(b""),
    st.integers(min_value=10, max_value=255).map(lambda value: bytes((value,))),
    st.binary(min_size=2, max_size=32),
)
_INVALID_ZLIB_DICTIONARY_PARAMETERS = st.one_of(
    st.just(b""),
    st.integers(min_value=10, max_value=255).map(lambda value: bytes((value,)) + b"x"),
    st.binary(min_size=1, max_size=1),
    st.integers(min_value=32770, max_value=32780).map(lambda size: b"x" * size),
)


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry(_FIRST_PARTY_STAGE_EXTENSIONS)


def test_public_stage_output_helpers_enforce_before_accumulation() -> None:
    output = bytearray(b"ab")

    extend_stage_output(
        output,
        b"cd",
        stage_id=_XOR_ID,
        max_output_size=4,
        operation="encode",
    )
    assert output == b"abcd"

    with pytest.raises(ProviderRejectedError) as rejection:
        extend_stage_output(
            output,
            b"e",
            stage_id=_XOR_ID,
            max_output_size=4,
            operation="encode",
        )

    assert output == b"abcd"
    assert rejection.value.resource_limit is not None
    error = rejection.value.resource_limit
    assert error.resource is CoreResource.INTERMEDIATE_BYTES
    assert error.scope == _XOR_ID
    assert error.observed == 5
    assert error.maximum == 4
    assert error.phase == "stage_encode"


def test_public_stage_output_size_helper_accepts_disabled_ceiling() -> None:
    require_stage_output_size(
        _XOR_ID,
        1_000_000,
        max_output_size=None,
        operation="decode",
    )


class _IdentityStage:
    extension_id = _XOR_ID
    descriptor = _XOR_DESCRIPTOR
    kind = ExtensionKind.STAGE

    def bind_encoder(self, parameters: bytes, /) -> _IdentityStage:
        require_no_parameters(_XOR_ID, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> _IdentityStage:
        require_no_parameters(_XOR_ID, parameters)
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return data

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return data


@pytest.mark.parametrize("stage_id", [DELTA8_STAGE_ID])
@settings(max_examples=30)
@given(parameters=st.binary(min_size=1, max_size=32))
def test_parameterless_extensions_reject_every_nonempty_parameter_block(
    stage_id: str, parameters: bytes
) -> None:
    registry = _stage_registry()
    recipe = Recipe(0, (StageSpec(stage_id, parameters),))

    with pytest.raises(PipelineError) as encode_error:
        encode_recipe(b"payload", recipe, registry, accounting=_accounting())
    with pytest.raises(PipelineError) as decode_error:
        decode_recipe(
            b"payload", recipe, registry, expected_size=7, accounting=_accounting()
        )

    assert stage_id in encode_error.value.reason
    assert encode_error.value.reason == decode_error.value.reason


@settings(max_examples=50)
@given(parameters=_INVALID_ZLIB_PARAMETERS)
def test_zlib_rejects_every_parameter_block_outside_its_contract(
    parameters: bytes,
) -> None:
    registry = _stage_registry()
    recipe = Recipe(0, (StageSpec(ZLIB_STAGE_ID, parameters),))

    with pytest.raises(PipelineError) as encode_error:
        encode_recipe(b"payload", recipe, registry, accounting=_accounting())
    with pytest.raises(PipelineError) as decode_error:
        decode_recipe(
            b"payload", recipe, registry, expected_size=7, accounting=_accounting()
        )

    assert "compression-level" in encode_error.value.reason
    assert encode_error.value.reason == decode_error.value.reason


@pytest.mark.parametrize("compression_level", range(10))
def test_zlib_parameter_encoder_owns_the_wire_representation(
    compression_level: int,
) -> None:
    value = ZlibParameters(compression_level)
    assert _ZLIB.encode_parameters(value) == bytes((compression_level,))
    assert _ZLIB.decode_parameters(bytes((compression_level,))) == value


@pytest.mark.parametrize("compression_level", (-1, 10, True, 1.5, "9", None))
def test_zlib_parameter_encoder_rejects_values_outside_the_contract(
    compression_level: object,
) -> None:
    error = (
        TypeError
        if not isinstance(compression_level, int) or isinstance(compression_level, bool)
        else ValueError
    )
    with pytest.raises(error):
        ZlibParameters(compression_level)  # type: ignore[arg-type]


@settings(max_examples=30)
@given(parameters=_INVALID_ZLIB_DICTIONARY_PARAMETERS)
def test_zlib_dictionary_rejects_parameter_blocks_outside_its_contract(
    parameters: bytes,
) -> None:
    registry = _stage_registry()
    recipe = Recipe(0, (StageSpec(ZLIB_DICTIONARY_STAGE_ID, parameters),))

    with pytest.raises(PipelineError, match=r"obst\.zlib@2"):
        encode_recipe(b"payload", recipe, registry, accounting=_accounting())
    with pytest.raises(PipelineError, match=r"obst\.zlib@2"):
        decode_recipe(
            b"payload", recipe, registry, expected_size=7, accounting=_accounting()
        )


@pytest.mark.parametrize(
    "dictionary",
    (b"x", b"d" * 32768),
    ids=("minimum", "maximum"),
)
def test_zlib_dictionary_parameter_encoder_owns_the_wire_representation(
    dictionary: bytes,
) -> None:
    value = ZlibDictionaryParameters(7, dictionary)
    assert _ZLIB_DICTIONARY.encode_parameters(value) == b"\x07" + dictionary
    assert _ZLIB_DICTIONARY.decode_parameters(b"\x07" + dictionary) == value


@pytest.mark.parametrize(
    ("compression_level", "dictionary", "error"),
    (
        (-1, b"dictionary", ValueError),
        (10, b"dictionary", ValueError),
        (True, b"dictionary", TypeError),
        (6, b"", ValueError),
        (6, b"x" * 32769, ValueError),
        (6, bytearray(b"dictionary"), TypeError),
    ),
    ids=(
        "level-below-range",
        "level-above-range",
        "boolean-level",
        "empty-dictionary",
        "oversized-dictionary",
        "non-bytes-dictionary",
    ),
)
def test_zlib_dictionary_parameter_encoder_rejects_invalid_values(
    compression_level: object,
    dictionary: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        ZlibDictionaryParameters(
            compression_level,  # type: ignore[arg-type]
            dictionary,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "recipe",
    [
        Recipe(0, ()),
        Recipe(1, (StageSpec(DELTA8_STAGE_ID),)),
        Recipe(2, (StageSpec(ZLIB_STAGE_ID, b"\x09"),)),
        Recipe(
            3,
            (
                StageSpec(
                    ZLIB_DICTIONARY_STAGE_ID,
                    _ZLIB_DICTIONARY.encode_parameters(
                        ZlibDictionaryParameters(9, bytes(range(256)))
                    ),
                ),
            ),
        ),
    ],
)
def test_first_party_extensions_enforce_output_limits(
    recipe: Recipe,
) -> None:
    data = bytes(range(256)) * 4
    registry = _stage_registry()
    baseline = encode_recipe(
        data,
        recipe,
        registry,
        accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, len(data) + 64)),
    )
    assert (
        encode_recipe(
            data,
            recipe,
            registry,
            accounting=_accounting(
                (CoreResource.INTERMEDIATE_BYTES, max(len(data), len(baseline)))
            ),
        )
        == baseline
    )
    assert (
        decode_recipe(
            baseline,
            recipe,
            registry,
            expected_size=len(data),
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, len(data))),
        )
        == data
    )
    with pytest.raises(ResourceLimitError):
        encode_recipe(
            data,
            recipe,
            registry,
            accounting=_accounting(
                (CoreResource.INTERMEDIATE_BYTES, max(len(data), len(baseline)) - 1)
            ),
        )
    with pytest.raises(ResourceLimitError):
        decode_recipe(
            baseline,
            recipe,
            registry,
            expected_size=len(data),
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, len(data) - 1)),
        )


def test_zlib_rejects_invalid_payload() -> None:
    registry = _stage_registry()

    with pytest.raises(PipelineError, match="invalid zlib payload"):
        decode_recipe(
            b"not zlib",
            Recipe(0, (StageSpec(ZLIB_STAGE_ID, b"\x06"),)),
            registry,
            expected_size=7,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 64)),
        )


@pytest.mark.parametrize(
    ("extension", "parameters"),
    (
        (_ZLIB, _ZLIB.encode_parameters(ZlibParameters(6))),
        (
            _ZLIB_DICTIONARY,
            _ZLIB_DICTIONARY.encode_parameters(
                ZlibDictionaryParameters(6, b"common-prefix:")
            ),
        ),
    ),
    ids=("dictionary-free", "preset-dictionary"),
)
@pytest.mark.parametrize(
    "malformation",
    (
        "truncated",
        "trailing-bytes",
        "concatenated-stream",
    ),
)
def test_zlib_rejects_payloads_that_are_not_exactly_one_complete_stream(
    extension: ZlibExtension | ZlibDictionaryExtension,
    parameters: bytes,
    malformation: str,
) -> None:
    logical = b"common-prefix:payload" * 8
    recipe = Recipe(0, (StageSpec(extension.extension_id, parameters),))
    encoded = encode_recipe(
        logical, recipe, _stage_registry(), accounting=_accounting()
    )
    malformed = {
        "truncated": encoded[:-1],
        "trailing-bytes": encoded + b"trailing",
        "concatenated-stream": encoded + encoded,
    }[malformation]

    with pytest.raises(PipelineError, match="invalid framing"):
        decode_recipe(
            malformed,
            recipe,
            _stage_registry(),
            expected_size=len(logical),
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 4096)),
        )


@pytest.mark.parametrize(
    ("logical", "encoded"),
    (
        (b"", b""),
        (b"\x00", b"\x00"),
        (b"\x00\x01\xff", b"\x00\x01\xfe"),
        (b"\xff\x00\x01", b"\xff\x01\x01"),
    ),
    ids=("empty", "zero", "wrap-backward", "wrap-forward"),
)
def test_delta8_known_answers(logical: bytes, encoded: bytes) -> None:
    recipe = Recipe(0, (StageSpec(DELTA8_STAGE_ID),))
    registry = _stage_registry()

    assert encode_recipe(logical, recipe, registry, accounting=_accounting()) == encoded
    assert (
        decode_recipe(
            encoded,
            recipe,
            registry,
            expected_size=len(logical),
            accounting=_accounting(),
        )
        == logical
    )


def test_delta8_state_resets_for_every_chunk() -> None:
    recipe = Recipe(0, (StageSpec(DELTA8_STAGE_ID),))
    registry = _stage_registry()

    assert tuple(
        encode_recipe(chunk, recipe, registry, accounting=_accounting())
        for chunk in (b"\x01", b"\x02")
    ) == (b"\x01", b"\x02")
    assert (
        encode_recipe(b"\x01\x02", recipe, registry, accounting=_accounting())
        == b"\x01\x01"
    )


def test_zlib_v1_rejects_a_preset_dictionary_stream() -> None:
    dictionary = b"common-prefix:" * 16
    encoder = stdlib_zlib.compressobj(6, zdict=dictionary)
    payload = encoder.compress(dictionary + b"value") + encoder.flush()

    with pytest.raises(PipelineError, match="forbids preset dictionaries"):
        decode_recipe(
            payload,
            Recipe(0, (StageSpec(ZLIB_STAGE_ID, b"\x06"),)),
            _stage_registry(),
            expected_size=len(dictionary) + 5,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 4096)),
        )


def test_zlib_v2_requires_a_preset_dictionary_stream() -> None:
    payload = stdlib_zlib.compress(b"ordinary zlib")
    parameters = _ZLIB_DICTIONARY.encode_parameters(
        ZlibDictionaryParameters(6, b"dictionary")
    )

    with pytest.raises(PipelineError, match="requires a preset-dictionary"):
        decode_recipe(
            payload,
            Recipe(0, (StageSpec(ZLIB_DICTIONARY_STAGE_ID, parameters),)),
            _stage_registry(),
            expected_size=13,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 64)),
        )


def test_zlib_v2_rejects_a_different_dictionary() -> None:
    encoder = stdlib_zlib.compressobj(6, zdict=b"correct dictionary")
    payload = encoder.compress(b"correct dictionary payload") + encoder.flush()
    parameters = _ZLIB_DICTIONARY.encode_parameters(
        ZlibDictionaryParameters(6, b"wrong dictionary")
    )

    with pytest.raises(PipelineError, match="identifier does not match"):
        decode_recipe(
            payload,
            Recipe(0, (StageSpec(ZLIB_DICTIONARY_STAGE_ID, parameters),)),
            _stage_registry(),
            expected_size=26,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 64)),
        )


def test_encode_and_decode_enforce_the_same_intermediate_limit() -> None:
    registry = _stage_registry()
    identity_recipe = Recipe(0, ())

    with pytest.raises(ResourceLimitError, match="intermediate_bytes"):
        encode_recipe(
            b"too large",
            identity_recipe,
            registry,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 2)),
        )
    with pytest.raises(ResourceLimitError, match="intermediate_bytes"):
        decode_recipe(
            b"too large",
            identity_recipe,
            registry,
            expected_size=9,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 2)),
        )


def test_executor_rejects_provider_outputs_that_violate_the_protocol() -> None:
    class InvalidOutputStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            return bytearray(data)  # type: ignore[return-value]

    registry = ExtensionRegistry((InvalidOutputStage(),))

    with pytest.raises(ExtensionContractError, match="provider must return bytes"):
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_XOR_ID),)),
            registry,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 64)),
        )


def test_executor_rejects_bytes_subclass_before_size_accounting() -> None:
    class MisleadingBytes(bytes):
        def __len__(self) -> int:
            return 0

    class InvalidOutputStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            return MisleadingBytes(b"larger than reported")

    registry = ExtensionRegistry((InvalidOutputStage(),))

    with pytest.raises(ExtensionContractError, match="provider must return bytes"):
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_XOR_ID),)),
            registry,
            accounting=_accounting(),
        )


def test_stage_execution_budget_spans_complete_recipe() -> None:
    recipe = Recipe(
        0,
        (StageSpec(DELTA8_STAGE_ID), StageSpec(DELTA8_STAGE_ID)),
    )

    with pytest.raises(ResourceLimitError) as error:
        encode_recipe(
            b"payload",
            recipe,
            _stage_registry(),
            accounting=_accounting((CoreResource.STAGE_EXECUTIONS, 1)),
        )

    assert error.value.resource is CoreResource.STAGE_EXECUTIONS
    assert error.value.observed == 2


def test_unexpected_provider_exceptions_have_stable_extension_context() -> None:
    class ExplodingStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            raise RuntimeError("provider bug")

    registry = ExtensionRegistry((ExplodingStage(),))

    with pytest.raises(ExtensionContractError) as error:
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_XOR_ID),)),
            registry,
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 64)),
        )

    assert error.value.extension_id == _XOR_ID
    assert error.value.capability == "encode execute"
    assert "provider raised RuntimeError: provider bug" == error.value.reason
    assert isinstance(error.value.__cause__, RuntimeError)


def test_provider_obst_errors_cannot_masquerade_as_core_failures() -> None:
    class PretendExtensionFailure(ObstError):
        pass

    class MisleadingStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            raise PretendExtensionFailure("not really an extension failure")

    with pytest.raises(ExtensionContractError) as error:
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_XOR_ID),)),
            ExtensionRegistry((MisleadingStage(),)),
            accounting=_accounting(),
        )

    assert error.value.extension_id == _XOR_ID
    assert error.value.capability == "encode execute"
    assert isinstance(error.value.__cause__, PretendExtensionFailure)


def test_wrong_provider_signature_fails_with_extension_context() -> None:
    class WrongSignatureExecutor:
        def encode(self) -> bytes:
            return b""

    class WrongSignatureStage:
        extension_id = _XOR_ID
        descriptor = _XOR_DESCRIPTOR
        kind = ExtensionKind.STAGE

        def bind_encoder(self, parameters: bytes, /) -> object:
            return WrongSignatureExecutor()

    registry = ExtensionRegistry((WrongSignatureStage(),))

    with pytest.raises(ExtensionContractError) as error:
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_XOR_ID),)),
            registry,
            accounting=_accounting(),
        )

    assert error.value.extension_id == _XOR_ID
    assert error.value.capability == "encode execute"
    assert isinstance(error.value.__cause__, TypeError)


@pytest.mark.parametrize(
    ("direction", "expected_ceiling"),
    [("encode", 2), ("decode", 1)],
)
def test_core_rechecks_provider_output_ceiling(
    direction: str,
    expected_ceiling: int,
) -> None:
    class OversizedStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            return b"oversized"

        def decode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            return b"oversized"

    registry = ExtensionRegistry((OversizedStage(),))
    recipe = Recipe(0, (StageSpec(_XOR_ID),))
    policy = _policy((CoreResource.INTERMEDIATE_BYTES, 2))

    with pytest.raises(
        ExtensionContractError,
        match=rf"above its {expected_ceiling}-byte output ceiling",
    ):
        if direction == "encode":
            encode_recipe(b"x", recipe, registry, accounting=ResourceAccounting(policy))
        else:
            decode_recipe(
                b"x",
                recipe,
                registry,
                expected_size=1,
                accounting=ResourceAccounting(policy),
            )


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_final_stage_receives_tighter_endpoint_ceiling(direction: str) -> None:
    received: list[int | None] = []

    class RecordingStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            received.append(max_output_size)
            return data

        def decode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            received.append(max_output_size)
            return data

    registry = ExtensionRegistry((RecordingStage(),))
    recipe = Recipe(0, (StageSpec(_XOR_ID),))
    policy = _policy(
        (CoreResource.ENCODED_CHUNK_BYTES, 1),
        (CoreResource.INTERMEDIATE_BYTES, 7),
    )

    if direction == "encode":
        ChunkEncoder(registry, accounting=ResourceAccounting(policy)).encode(
            b"x",
            stream_id=0,
            sequence=0,
            recipe=recipe,
        )
    else:
        decode_recipe(
            b"x",
            recipe,
            registry,
            expected_size=1,
            accounting=ResourceAccounting(policy),
        )

    assert received == [1]


def test_provider_output_helper_preserves_structured_resource_limit() -> None:
    class BoundedStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            require_stage_output_size(
                _XOR_ID,
                3,
                max_output_size=max_output_size,
                operation="encode",
            )
            return b"xxx"

    with pytest.raises(ResourceLimitError) as error:
        encode_recipe(
            b"x",
            Recipe(0, (StageSpec(_XOR_ID),)),
            ExtensionRegistry((BoundedStage(),)),
            accounting=_accounting((CoreResource.INTERMEDIATE_BYTES, 2)),
        )

    assert error.value.resource is CoreResource.INTERMEDIATE_BYTES
    assert error.value.scope == _XOR_ID
    assert error.value.phase == "stage_encode"


def test_expected_payload_rejection_becomes_structured_pipeline_error() -> None:
    class RejectingStage(_IdentityStage):
        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            raise ProviderRejectedError("payload rejected")

    with pytest.raises(PipelineError) as error:
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_XOR_ID),)),
            ExtensionRegistry((RejectingStage(),)),
            accounting=_accounting(),
        )

    assert error.value.stage_id == _XOR_ID
    assert error.value.direction == "encode"
    assert error.value.phase == "execute"
    assert error.value.reason == "payload rejected"
