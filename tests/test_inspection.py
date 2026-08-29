from __future__ import annotations

import io
from typing import cast

import pytest

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ContainerWriter,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionRegistry,
    ExtensionRegistryBuilder,
    InspectionInterpretation,
    InspectionInterpretationPolicy,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
    encode_chunk_once,
    inspect_container,
    materialize_stream,
    require_no_parameters,
)
from obst.core.extensions import ExtensionKind
from tests.support_extensions import CompressionExtension as ZlibExtension
from tests.support_extensions import IdentityExtension as RawExtension
from tests.support_resources import accounting as _accounting

RAW_STAGE_ID = RawExtension.extension_id
ZLIB_STAGE_ID = ZlibExtension.extension_id

_CUSTOM_STAGE_ID = "org.example/inspection-only@1"
_PROFILE_ID = "org.example/inspection-profile@1"
_CUSTOM_DESCRIPTOR = ExtensionDescriptor()
_PROFILE_DESCRIPTOR = ExtensionDescriptor()


def _empty_interpretation(_data: bytes) -> InspectionInterpretation:
    return InspectionInterpretation()


class _IdentityEncoderStage:
    extension_id = _CUSTOM_STAGE_ID
    descriptor = _CUSTOM_DESCRIPTOR
    kind = ExtensionKind.STAGE

    def bind_encoder(self, parameters: bytes, /) -> _IdentityEncoderStage:
        require_no_parameters(self.extension_id, parameters)
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        assert max_output_size is None or len(data) <= max_output_size
        return data


class _ExplodingDecoderStage:
    extension_id = _CUSTOM_STAGE_ID
    descriptor = _CUSTOM_DESCRIPTOR
    kind = ExtensionKind.STAGE

    def bind_decoder(self, parameters: bytes, /) -> _ExplodingDecoderStage:
        require_no_parameters(self.extension_id, parameters)
        return self

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        raise AssertionError("inspection must never execute a decoder")


def test_interpretation_policy_requires_canonical_extension_ids() -> None:
    with pytest.raises(TypeError, match="exact frozenset"):
        InspectionInterpretationPolicy(cast(frozenset[str], {_CUSTOM_STAGE_ID}))
    with pytest.raises(TypeError, match="exact strings"):
        InspectionInterpretationPolicy(cast(frozenset[str], frozenset({1})))
    with pytest.raises(ValueError, match="invalid OBST extension id"):
        InspectionInterpretationPolicy(frozenset({"INVALID"}))


def test_inspection_retains_actual_usage_by_stream_recipe_and_stage() -> None:
    manifest = Manifest(
        recipes=(
            Recipe(0, (StageSpec(RAW_STAGE_ID),)),
            Recipe(1, (StageSpec(ZLIB_STAGE_ID, b"\x06"),)),
        ),
        streams=(
            Stream(0, BYTES_STREAM_TYPE, 0),
            Stream(1, BYTES_STREAM_TYPE, 1),
        ),
    )
    target = io.BytesIO()
    registry = ExtensionRegistry((RawExtension(), ZlibExtension()))
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            b"raw",
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.write_chunk(
        encode_chunk_once(
            b"compressed" * 20,
            stream_id=0,
            sequence=1,
            recipe=manifest.recipe(1),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.write_chunk(
        encode_chunk_once(
            b"first" * 20,
            stream_id=1,
            sequence=0,
            recipe=manifest.recipe(1),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.write_chunk(
        encode_chunk_once(
            b"second" * 20,
            stream_id=1,
            sequence=1,
            recipe=manifest.recipe(1),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.finish()

    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
        registry=registry,
    )

    assert [recipe.chunk_count for recipe in inspection.recipes] == [1, 3]
    assert inspection.summary.chunk_count == 4
    assert inspection.resources.extension_count == 3
    assert inspection.resources.recipe_count == 2
    assert inspection.resources.stream_count == 2
    assert inspection.resources.total_stage_count == 2
    assert inspection.resources.max_stages_per_recipe == 1
    assert inspection.resources.max_logical_chunk_size == 200
    assert inspection.resources.stage_executions == 4
    assert inspection.resources.max_materialized_stream_size == 220
    assert [
        [(usage.recipe_id, usage.chunk_count) for usage in stream.recipe_usage]
        for stream in inspection.streams
    ] == [[(0, 1), (1, 1)], [(1, 2)]]
    capabilities = {stage.stage_id: stage for stage in inspection.stage_capabilities}
    assert [
        (usage.recipe_id, usage.chunk_count)
        for usage in capabilities[RAW_STAGE_ID].used_chunks_by_recipe
    ] == [(0, 1)]
    assert [
        (usage.recipe_id, usage.chunk_count)
        for usage in capabilities[ZLIB_STAGE_ID].used_chunks_by_recipe
    ] == [(1, 3)]


def test_unused_unknown_stage_is_declared_but_not_required() -> None:
    manifest = Manifest(
        recipes=(
            Recipe(0, (StageSpec(RAW_STAGE_ID),)),
            Recipe(1, (StageSpec(_CUSTOM_STAGE_ID),)),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    complete_writer_registry = ExtensionRegistry(
        (RawExtension(), _IdentityEncoderStage())
    )
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            b"payload",
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=complete_writer_registry,
            accounting=_accounting(),
        )
    )
    writer.finish()

    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
        registry=ExtensionRegistry((RawExtension(),)),
    )

    assert inspection.missing_declared_stages == (_CUSTOM_STAGE_ID,)
    assert inspection.missing_required_stages == ()
    assert inspection.required_decoders_available
    custom = next(
        stage
        for stage in inspection.stage_capabilities
        if stage.stage_id == _CUSTOM_STAGE_ID
    )
    assert custom.declared_recipe_ids == (1,)
    assert custom.used_recipe_ids == ()
    assert not custom.required


def test_inspection_observes_decoder_capability_without_executing_it() -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(_CUSTOM_STAGE_ID),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    writer_registry = ExtensionRegistry((_IdentityEncoderStage(),))
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            b"payload",
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=writer_registry,
            accounting=_accounting(),
        )
    )
    writer.finish()
    reader_registry = ExtensionRegistry((_ExplodingDecoderStage(),))

    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
        registry=reader_registry,
    )

    assert inspection.required_decoders_available
    assert inspection.logical_recovery.value == "not_attempted"
    assert inspection.encoded_size == len(target.getvalue())
    assert inspection.manifest == manifest
    assert inspection.resources.manifest_size > 0
    assert inspection.resources.extension_count == 2
    assert inspection.resources.total_stage_count == 1


def test_inspection_uses_the_registry_snapshot_from_operation_start() -> None:
    builder = ExtensionRegistryBuilder()

    class MutatingStage:
        extension_id = _CUSTOM_STAGE_ID
        descriptor = _CUSTOM_DESCRIPTOR
        kind = ExtensionKind.STAGE
        calls = 0

        def interpret_parameters(
            self,
            parameters: bytes,
            /,
        ) -> InspectionInterpretation:
            self.calls += 1
            builder.register(_ExplodingDecoderStage())
            return InspectionInterpretation()

    interpreter = MutatingStage()
    builder.register(interpreter)
    registry = builder.build()
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(_CUSTOM_STAGE_ID),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    ContainerWriter(target, manifest, accounting=_accounting()).finish()

    structural_inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
        registry=registry,
    )

    assert interpreter.calls == 0
    assert structural_inspection.recipes[0].stages[0].parameters is None
    assert not builder.build().can_decode(_CUSTOM_STAGE_ID)

    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
        registry=registry,
        interpretation_policy=InspectionInterpretationPolicy(
            frozenset({_CUSTOM_STAGE_ID})
        ),
    )

    capability = next(
        stage
        for stage in inspection.stage_capabilities
        if stage.stage_id == _CUSTOM_STAGE_ID
    )
    assert interpreter.calls == 1
    assert inspection.recipes[0].stages[0].parameters is not None
    assert not capability.decoder_available
    assert not registry.can_decode(_CUSTOM_STAGE_ID)
    assert builder.build().can_decode(_CUSTOM_STAGE_ID)


def test_interpretation_policy_is_an_explicit_extension_allowlist() -> None:
    class CountingStage:
        extension_id = _CUSTOM_STAGE_ID
        descriptor = _CUSTOM_DESCRIPTOR
        kind = ExtensionKind.STAGE

        def __init__(self) -> None:
            self.calls = 0

        def interpret_parameters(
            self,
            parameters: bytes,
            /,
        ) -> InspectionInterpretation:
            self.calls += 1
            return InspectionInterpretation()

    class CountingProfile:
        extension_id = _PROFILE_ID
        descriptor = _PROFILE_DESCRIPTOR
        kind = ExtensionKind.STREAM_PROFILE

        def __init__(self) -> None:
            self.calls = 0

        def interpret_metadata(
            self,
            metadata: bytes,
            /,
        ) -> InspectionInterpretation:
            self.calls += 1
            return InspectionInterpretation()

    stage_interpreter = CountingStage()
    profile_interpreter = CountingProfile()
    registry = ExtensionRegistry((stage_interpreter, profile_interpreter))
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(_CUSTOM_STAGE_ID),)),),
        streams=(Stream(0, _PROFILE_ID, 0, b"opaque"),),
    )
    target = io.BytesIO()
    ContainerWriter(target, manifest, accounting=_accounting()).finish()
    encoded = target.getvalue()

    structural = inspect_container(
        ContainerReader(io.BytesIO(encoded), accounting=_accounting()),
        registry=registry,
    )

    assert stage_interpreter.calls == 0
    assert profile_interpreter.calls == 0
    assert structural.recipes[0].stages[0].parameters is None
    assert structural.streams[0].metadata is None

    interpreted = inspect_container(
        ContainerReader(io.BytesIO(encoded), accounting=_accounting()),
        registry=registry,
        interpretation_policy=InspectionInterpretationPolicy(
            frozenset({_CUSTOM_STAGE_ID})
        ),
    )

    assert stage_interpreter.calls == 1
    assert profile_interpreter.calls == 0
    assert interpreted.recipes[0].stages[0].parameters is not None
    assert interpreted.streams[0].metadata is None


@pytest.mark.parametrize("capability", ("parameters", "metadata"))
def test_interpreter_member_access_uses_the_extension_error_boundary(
    capability: str,
) -> None:
    class ChangingStage:
        extension_id = _CUSTOM_STAGE_ID
        descriptor = _CUSTOM_DESCRIPTOR
        kind = ExtensionKind.STAGE

        def __init__(self) -> None:
            self.accesses = 0

        @property
        def interpret_parameters(self) -> object:
            self.accesses += 1
            if self.accesses == 1:
                return _empty_interpretation
            raise RuntimeError("parameter getter changed")

    class ChangingProfile:
        extension_id = _PROFILE_ID
        descriptor = _PROFILE_DESCRIPTOR
        kind = ExtensionKind.STREAM_PROFILE

        def __init__(self) -> None:
            self.accesses = 0

        @property
        def interpret_metadata(self) -> object:
            self.accesses += 1
            if self.accesses == 1:
                return _empty_interpretation
            raise RuntimeError("metadata getter changed")

    extension = ChangingStage() if capability == "parameters" else ChangingProfile()
    registry = ExtensionRegistry((extension,))
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(_CUSTOM_STAGE_ID),)),),
        streams=(Stream(0, _PROFILE_ID, 0, b"opaque"),),
    )
    target = io.BytesIO()
    ContainerWriter(target, manifest, accounting=_accounting()).finish()
    extension_id = _CUSTOM_STAGE_ID if capability == "parameters" else _PROFILE_ID

    with pytest.raises(ExtensionContractError, match="getter changed"):
        inspect_container(
            ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
            registry=registry,
            interpretation_policy=InspectionInterpretationPolicy(
                frozenset({extension_id})
            ),
        )


def test_recoverable_payload_does_not_imply_understood_stream_semantics() -> None:
    stream_type = "org.example/opaque-records@1"
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RAW_STAGE_ID),)),),
        streams=(Stream(0, stream_type, 0, b"application-owned metadata"),),
    )
    registry = ExtensionRegistry((RawExtension(),))
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    writer.write_chunk(
        encode_chunk_once(
            b"recoverable logical bytes",
            stream_id=0,
            sequence=0,
            recipe=manifest.recipe(0),
            registry=registry,
            accounting=_accounting(),
        )
    )
    writer.finish()

    encoded = target.getvalue()
    inspection = inspect_container(
        ContainerReader(io.BytesIO(encoded), accounting=_accounting()),
        registry=registry,
    )

    assert inspection.required_decoders_available
    assert inspection.streams[0].metadata is None
    assert inspection.streams[0].declaration.metadata == b"application-owned metadata"
    assert (
        materialize_stream(
            ContainerReader(io.BytesIO(encoded), accounting=_accounting()), 0, registry
        )
        == b"recoverable logical bytes"
    )


def test_empty_stream_has_zero_chunk_resource_footprint() -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RAW_STAGE_ID),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    ContainerWriter(target, manifest, accounting=_accounting()).finish()

    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting())
    )

    assert inspection.summary.chunk_count == 0
    assert inspection.resources.max_encoded_chunk_size == 0
    assert inspection.resources.max_logical_chunk_size == 0
    assert inspection.summary.logical_size == 0
    assert inspection.resources.stage_executions == 0
    assert inspection.resources.max_materialized_stream_size == 0


def test_resource_footprint_multiplies_chunks_by_recipe_stages() -> None:
    manifest = Manifest(
        recipes=(
            Recipe(
                0,
                (
                    StageSpec(RAW_STAGE_ID),
                    StageSpec(ZLIB_STAGE_ID, b"\x06"),
                ),
            ),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    registry = ExtensionRegistry((RawExtension(), ZlibExtension()))
    target = io.BytesIO()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    for sequence, payload in enumerate((b"first", b"second")):
        writer.write_chunk(
            encode_chunk_once(
                payload,
                stream_id=0,
                sequence=sequence,
                recipe=manifest.recipe(0),
                registry=registry,
                accounting=_accounting(),
            )
        )
    writer.finish()

    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting())
    )

    assert inspection.resources.total_stage_count == 2
    assert inspection.resources.max_stages_per_recipe == 2
    assert inspection.resources.stage_executions == 4
