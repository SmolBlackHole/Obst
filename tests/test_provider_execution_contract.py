from __future__ import annotations

import io

import pytest

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ContainerWriter,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionRegistry,
    LogicalStreamDescriptor,
    LogicalStreamSource,
    Manifest,
    MissingStageError,
    PipelineError,
    ProviderRejectedError,
    Recipe,
    RecipeSpec,
    ResourceLimitError,
    ResourceLimits,
    StageSpec,
    Stream,
    decode_recipe,
    encode_chunk_once,
    encode_recipe,
    materialize_stream,
)
from obst.core.extensions import ExtensionKind
from obst.core.pipeline import RecipeDecoder, RecipeEncoder
from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)

_FIRST_STAGE_ID = "org.example/first@1"
_SECOND_STAGE_ID = "org.example/second@1"
_MISSING_STAGE_ID = "org.example/missing@1"
_UNUSED_STAGE_ID = "org.example/unused@1"
_REJECTING_STAGE_ID = "org.example/rejecting@1"


class _TracingStage:
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def __init__(
        self,
        stage_id: str,
        events: list[str],
        ceilings: list[tuple[str, int | None]] | None = None,
    ) -> None:
        self.extension_id = stage_id
        self._events = events
        self._ceilings = ceilings

    def bind_encoder(self, parameters: bytes, /) -> _TracingEncoder:
        self._events.append(f"{self.extension_id}:bind_encoder")
        return _TracingEncoder(self.extension_id, self._events, self._ceilings)

    def bind_decoder(self, parameters: bytes, /) -> _TracingDecoder:
        self._events.append(f"{self.extension_id}:bind_decoder")
        return _TracingDecoder(self.extension_id, self._events, self._ceilings)


class _TracingEncoder:
    def __init__(
        self,
        stage_id: str,
        events: list[str],
        ceilings: list[tuple[str, int | None]] | None,
    ) -> None:
        self._stage_id = stage_id
        self._events = events
        self._ceilings = ceilings

    def encode(self, data: bytes, /, *, max_output_size: int | None) -> bytes:
        self._events.append(f"{self._stage_id}:encode")
        if self._ceilings is not None:
            self._ceilings.append(("encode", max_output_size))
        return data


class _TracingDecoder:
    def __init__(
        self,
        stage_id: str,
        events: list[str],
        ceilings: list[tuple[str, int | None]] | None,
    ) -> None:
        self._stage_id = stage_id
        self._events = events
        self._ceilings = ceilings

    def decode(self, data: bytes, /, *, max_output_size: int | None) -> bytes:
        self._events.append(f"{self._stage_id}:decode")
        if self._ceilings is not None:
            self._ceilings.append(("decode", max_output_size))
        return data


class _ExplodingUnusedStage:
    extension_id = _UNUSED_STAGE_ID
    descriptor = ExtensionDescriptor()
    kind = ExtensionKind.STAGE

    def bind_decoder(self, parameters: bytes, /) -> _TracingDecoder:
        raise AssertionError("unused recipe decoder was bound")


class _RejectingStage:
    extension_id = _REJECTING_STAGE_ID
    descriptor = ExtensionDescriptor()
    kind = ExtensionKind.STAGE

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def bind_encoder(self, parameters: bytes, /) -> _TracingEncoder:
        self._events.append("bind_encoder")
        raise ProviderRejectedError("parameters rejected during preflight")


class _BytesSubclass(bytes):
    pass


class _ForgedResourceRejection(ProviderRejectedError):
    @property
    def reason(self) -> str:
        raise RuntimeError("provider reason property must not be inspected")

    @reason.setter
    def reason(self, value: str) -> None:
        self._stored_reason = value

    @property
    def resource_limit(self) -> ResourceLimitError:
        raise AssertionError("provider property must not be inspected")


class _ForgingStage:
    extension_id = "org.example/forging@1"
    descriptor = ExtensionDescriptor()
    kind = ExtensionKind.STAGE

    def bind_encoder(self, parameters: bytes, /) -> _ForgingStage:
        return self

    def encode(self, data: bytes, /, *, max_output_size: int | None) -> bytes:
        raise _ForgedResourceRejection("ordinary provider rejection")


def test_recipe_callbacks_follow_directional_stage_order() -> None:
    events: list[str] = []
    registry = ExtensionRegistry(
        (
            _TracingStage(_FIRST_STAGE_ID, events),
            _TracingStage(_SECOND_STAGE_ID, events),
        )
    )
    recipe = Recipe(
        0,
        (
            StageSpec(_FIRST_STAGE_ID, b"first"),
            StageSpec(_SECOND_STAGE_ID, b"second"),
        ),
    )

    encoded = encode_recipe(b"payload", recipe, registry)

    assert encoded == b"payload"
    assert events == [
        f"{_FIRST_STAGE_ID}:bind_encoder",
        f"{_SECOND_STAGE_ID}:bind_encoder",
        f"{_FIRST_STAGE_ID}:encode",
        f"{_SECOND_STAGE_ID}:encode",
    ]

    events.clear()
    decoded = decode_recipe(encoded, recipe, registry, expected_size=len(encoded))

    assert decoded == b"payload"
    assert events == [
        f"{_SECOND_STAGE_ID}:bind_decoder",
        f"{_FIRST_STAGE_ID}:bind_decoder",
        f"{_SECOND_STAGE_ID}:decode",
        f"{_FIRST_STAGE_ID}:decode",
    ]


def test_prepared_recipes_bind_once_for_repeated_execution() -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))

    encoder = RecipeEncoder(registry)
    encoder.preflight((recipe,))
    assert encoder.encode(b"first", recipe) == b"first"
    assert encoder.encode(b"second", recipe) == b"second"

    decoder = RecipeDecoder(registry)
    assert decoder.decode(b"first", recipe, expected_size=5) == b"first"
    assert decoder.decode(b"second", recipe, expected_size=6) == b"second"

    assert events == [
        f"{_FIRST_STAGE_ID}:bind_encoder",
        f"{_FIRST_STAGE_ID}:encode",
        f"{_FIRST_STAGE_ID}:encode",
        f"{_FIRST_STAGE_ID}:bind_decoder",
        f"{_FIRST_STAGE_ID}:decode",
        f"{_FIRST_STAGE_ID}:decode",
    ]


def test_encoder_resolves_all_pending_recipes_before_any_bind_callback() -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    valid_recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))
    missing_recipe = Recipe(1, (StageSpec(_MISSING_STAGE_ID),))

    with pytest.raises(MissingStageError) as error:
        RecipeEncoder(registry).preflight((valid_recipe, missing_recipe))

    assert error.value.stage_id == _MISSING_STAGE_ID
    assert events == []


def test_recipe_decoder_binds_only_recipes_that_are_executed() -> None:
    events: list[str] = []
    registry = ExtensionRegistry(
        (
            _TracingStage(_FIRST_STAGE_ID, events),
            _ExplodingUnusedStage(),
        )
    )
    used_recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))

    assert (
        RecipeDecoder(registry).decode(
            b"payload",
            used_recipe,
            expected_size=7,
        )
        == b"payload"
    )
    assert events == [
        f"{_FIRST_STAGE_ID}:bind_decoder",
        f"{_FIRST_STAGE_ID}:decode",
    ]


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_recipe_sessions_account_logical_bytes_across_calls(direction: str) -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))
    limits = ResourceLimits(max_total_logical_bytes=7)

    if direction == "encode":
        session = RecipeEncoder(registry, limits=limits)
        session.preflight((recipe,))
        assert session.encode(b"four", recipe) == b"four"
        with pytest.raises(ResourceLimitError) as error:
            session.encode(b"more", recipe)
    else:
        decoder = RecipeDecoder(registry, limits=limits)
        assert decoder.decode(b"four", recipe, expected_size=4) == b"four"
        with pytest.raises(ResourceLimitError) as error:
            decoder.decode(b"more", recipe, expected_size=4)

    assert error.value.resource == "logical_bytes"
    assert error.value.observed == 8


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_recipe_sessions_refuse_impossible_work_before_binding(direction: str) -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))
    limits = ResourceLimits(max_total_logical_bytes=0)

    with pytest.raises(ResourceLimitError):
        if direction == "encode":
            RecipeEncoder(registry, limits=limits).encode(b"x", recipe)
        else:
            RecipeDecoder(registry, limits=limits).decode(
                b"x",
                recipe,
                expected_size=1,
            )

    assert events == []


def test_encode_resolves_complete_recipe_before_first_provider_callback() -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID), StageSpec(_MISSING_STAGE_ID)))

    with pytest.raises(MissingStageError) as error:
        encode_recipe(b"payload", recipe, registry)

    assert error.value.stage_id == _MISSING_STAGE_ID
    assert events == []


def test_decode_resolves_complete_recipe_before_first_provider_callback() -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    recipe = Recipe(0, (StageSpec(_MISSING_STAGE_ID), StageSpec(_FIRST_STAGE_ID)))

    with pytest.raises(MissingStageError) as error:
        decode_recipe(b"payload", recipe, registry, expected_size=7)

    assert error.value.stage_id == _MISSING_STAGE_ID
    assert events == []


def test_decode_does_not_bind_provider_for_unused_recipe() -> None:
    events: list[str] = []
    used_stage = _TracingStage(_FIRST_STAGE_ID, events)
    used_recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))
    unused_recipe = Recipe(1, (StageSpec(_UNUSED_STAGE_ID),))
    manifest = Manifest(
        recipes=(used_recipe, unused_recipe),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest)
    writer.write_chunk(
        encode_chunk_once(
            b"payload",
            stream_id=0,
            sequence=0,
            recipe=used_recipe,
            registry=ExtensionRegistry((used_stage,)),
        )
    )
    writer.finish()
    events.clear()

    recovered = materialize_stream(
        ContainerReader(io.BytesIO(target.getvalue())),
        0,
        ExtensionRegistry((used_stage, _ExplodingUnusedStage())),
    )

    assert recovered == b"payload"
    assert events == [
        f"{_FIRST_STAGE_ID}:bind_decoder",
        f"{_FIRST_STAGE_ID}:decode",
    ]


def test_encoder_parameter_preflight_happens_before_container_header_write() -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_RejectingStage(events),))
    source = LogicalStreamSource.from_bytes(
        LogicalStreamDescriptor(
            BYTES_STREAM_TYPE,
            b"",
            RecipeSpec((StageSpec(_REJECTING_STAGE_ID, b"invalid"),)),
        ),
        b"payload",
        chunk_size=len(b"payload"),
    )
    target = io.BytesIO()

    with pytest.raises(PipelineError) as caught:
        FixedPackagerExtension().prepare_package(
            FixedPackageRequest(registry, (source,))
        ).write_to(target)

    assert caught.value.stage_id == _REJECTING_STAGE_ID
    assert caught.value.direction == "encode"
    assert caught.value.phase == "bind"
    assert caught.value.reason == "parameters rejected during preflight"
    assert events == ["bind_encoder"]
    assert target.getvalue() == b""


def test_provider_rejection_subclass_is_a_contract_failure() -> None:
    with pytest.raises(ExtensionContractError) as caught:
        encode_recipe(
            b"payload",
            Recipe(0, (StageSpec(_ForgingStage.extension_id),)),
            ExtensionRegistry((_ForgingStage(),)),
        )

    assert caught.value.extension_id == _ForgingStage.extension_id
    assert caught.value.capability == "encode execute"
    assert caught.value.reason == "provider must raise an exact ProviderRejectedError"


def test_recipe_input_bytes_subclasses_are_rejected_before_provider_callback() -> None:
    events: list[str] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events),))
    recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))

    with pytest.raises(TypeError, match="recipe input must be exact bytes"):
        encode_recipe(_BytesSubclass(b"payload"), recipe, registry)
    with pytest.raises(TypeError, match="recipe input must be exact bytes"):
        decode_recipe(
            _BytesSubclass(b"payload"),
            recipe,
            registry,
            expected_size=7,
        )

    assert events == []


def test_stage_parameter_subclasses_are_rejected_before_provider_callback() -> None:
    events: list[str] = []

    with pytest.raises(TypeError):
        Recipe(0, (StageSpec(_FIRST_STAGE_ID, _BytesSubclass(b"parameters")),))

    assert events == []


def test_output_ceiling_reaches_both_directional_executors() -> None:
    events: list[str] = []
    ceilings: list[tuple[str, int | None]] = []
    registry = ExtensionRegistry((_TracingStage(_FIRST_STAGE_ID, events, ceilings),))
    recipe = Recipe(0, (StageSpec(_FIRST_STAGE_ID),))

    encode_recipe(b"data", recipe, registry)
    decode_recipe(b"data", recipe, registry, expected_size=4)

    assert ceilings == [
        ("encode", 64 * 1024 * 1024),
        ("decode", 4),
    ]
