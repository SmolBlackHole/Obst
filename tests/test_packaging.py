from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import fields
from typing import Self, cast

import pytest

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ExtensionDescriptor,
    ExtensionRegistry,
    LogicalStreamDescriptor,
    LogicalStreamSource,
    MissingStageError,
    OperationStateError,
    PackageResult,
    PackageWriteOperation,
    PackagingError,
    PipelineError,
    ProviderRejectedError,
    RecipeSpec,
    ResourceLimitError,
    ResourceLimits,
    SourceConsumedError,
    StageSpec,
    iter_decoded_chunks,
    materialize_stream,
)
from obst.core.extensions import ExtensionKind
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import ZlibExtension
from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)
from obst_defaults.transforms.delta8 import Delta8Extension

_RAW = RecipeSpec((StageSpec(RawExtension.extension_id),))
_DELTA_ZLIB = RecipeSpec(
    (
        StageSpec(Delta8Extension.extension_id),
        StageSpec(ZlibExtension.extension_id, b"\x09"),
    )
)
_CUSTOM_STREAM_TYPE = "org.example/records@1"


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry((RawExtension(), Delta8Extension(), ZlibExtension()))


def _source(
    data: bytes,
    *,
    stream_type: str = BYTES_STREAM_TYPE,
    metadata: bytes = b"",
    recipe: RecipeSpec = _RAW,
    chunk_size: int = 4,
) -> LogicalStreamSource:
    return LogicalStreamSource.from_bytes(
        LogicalStreamDescriptor(stream_type, metadata, recipe),
        data,
        chunk_size=chunk_size,
    )


def _example_sources() -> tuple[LogicalStreamSource, ...]:
    return (
        _source(b"abcdefgh", metadata=b"first"),
        _source(b"", metadata=b"empty"),
        _source(
            bytes(range(64)) * 4,
            stream_type=_CUSTOM_STREAM_TYPE,
            metadata=b"records-v1",
            recipe=_DELTA_ZLIB,
            chunk_size=31,
        ),
    )


def _fixed_operation(
    registry: ExtensionRegistry,
    sources: tuple[LogicalStreamSource, ...],
    *,
    limits: ResourceLimits | None = None,
) -> PackageWriteOperation:
    request = (
        FixedPackageRequest(registry, sources)
        if limits is None
        else FixedPackageRequest(registry, sources, limits)
    )
    return FixedPackagerExtension().prepare_package(request)


def _package(
    target: io.BytesIO,
    registry: ExtensionRegistry,
    sources: tuple[LogicalStreamSource, ...],
    *,
    limits: ResourceLimits | None = None,
) -> PackageResult:
    return _fixed_operation(registry, sources, limits=limits).write_to(target)


def test_fixed_packager_preserves_stream_identity_and_logical_bytes() -> None:
    target = io.BytesIO()

    registry = _stage_registry()
    result = _package(target, registry, _example_sources())

    reader = ContainerReader(io.BytesIO(target.getvalue()))
    recovered = [bytearray() for _ in result.streams]
    for chunk, logical_bytes in iter_decoded_chunks(reader, registry):
        recovered[chunk.stream_id].extend(logical_bytes)
    assert tuple(bytes(data) for data in recovered) == (
        b"abcdefgh",
        b"",
        bytes(range(64)) * 4,
    )
    assert tuple(
        (stream.stream_type, stream.metadata, stream.default_recipe_id)
        for stream in result.manifest.streams
    ) == (
        (BYTES_STREAM_TYPE, b"first", 0),
        (BYTES_STREAM_TYPE, b"empty", 0),
        (_CUSTOM_STREAM_TYPE, b"records-v1", 1),
    )
    assert [recipe.recipe_id for recipe in result.manifest.recipes] == [0, 1]
    assert result.encoded_size == len(target.getvalue())
    assert result.chunk_count == sum(stream.chunk_count for stream in result.streams)


def test_fixed_packaging_is_deterministic_for_equal_inputs() -> None:
    first = io.BytesIO()
    second = io.BytesIO()

    first_result = _package(first, _stage_registry(), _example_sources())
    second_result = _package(second, _stage_registry(), _example_sources())

    assert first.getvalue() == second.getvalue()
    assert first_result == second_result


def test_prepared_package_operation_is_single_use() -> None:
    operation = _fixed_operation(_stage_registry(), (_source(b"payload"),))

    operation.write_to(io.BytesIO())

    with pytest.raises(OperationStateError, match="consumed state"):
        operation.write_to(io.BytesIO())


def test_packager_writes_each_chunk_before_requesting_the_next() -> None:
    target = io.BytesIO()

    def chunks() -> Iterator[bytes]:
        size_before_first = len(target.getvalue())
        yield b"first"
        assert len(target.getvalue()) > size_before_first
        size_before_second = len(target.getvalue())
        yield b"second"
        assert len(target.getvalue()) > size_before_second

    source = LogicalStreamSource(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", _RAW),
        chunks(),
        max_chunk_bytes=len(b"second"),
    )

    registry = _stage_registry()
    result = _package(target, registry, (source,))

    assert result.chunk_count == 2
    assert (
        materialize_stream(ContainerReader(io.BytesIO(target.getvalue())), 0, registry)
        == b"firstsecond"
    )
    with pytest.raises(SourceConsumedError, match="already been consumed"):
        source.iter_chunks()


def test_packager_rejects_invalid_chunk_type_after_claiming_source() -> None:
    def invalid_chunks() -> Iterator[bytes]:
        yield b"valid"
        yield cast(bytes, bytearray(b"mutable"))

    source = LogicalStreamSource(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", _RAW),
        invalid_chunks(),
        max_chunk_bytes=len(b"mutable"),
    )

    with pytest.raises(PackagingError, match="not exact bytes"):
        _package(io.BytesIO(), _stage_registry(), (source,))

    with pytest.raises(SourceConsumedError, match="already been consumed"):
        source.iter_chunks()


def test_packager_refuses_declared_chunk_limit_before_consuming_source() -> None:
    consumed = False

    def chunks() -> Iterator[bytes]:
        nonlocal consumed
        consumed = True
        yield b"oversized"

    source = LogicalStreamSource(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", _RAW),
        chunks(),
        max_chunk_bytes=9,
    )

    with pytest.raises(ResourceLimitError) as error:
        _package(
            io.BytesIO(),
            _stage_registry(),
            (source,),
            limits=ResourceLimits(max_logical_chunk_bytes=8),
        )

    assert error.value.resource == "logical_chunk_bytes"
    assert not consumed


def test_packager_refuses_manifest_limits_before_provider_validation() -> None:
    validation_calls = 0

    class CountingExtension:
        extension_id = "org.example/counting@1"
        kind = ExtensionKind.STAGE
        descriptor = ExtensionDescriptor()

        def bind_encoder(self, parameters: bytes, /) -> Self:
            nonlocal validation_calls
            validation_calls += 1
            return self

        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            return data

    registry = ExtensionRegistry((CountingExtension(),))
    recipe = RecipeSpec(
        (
            StageSpec(CountingExtension.extension_id),
            StageSpec(CountingExtension.extension_id),
        )
    )
    source = _source(b"payload", recipe=recipe)
    target = io.BytesIO()

    with pytest.raises(ResourceLimitError) as error:
        _package(
            target,
            registry,
            (source,),
            limits=ResourceLimits(max_stages_per_recipe=1),
        )

    assert error.value.resource == "stages_per_recipe"
    assert validation_calls == 0
    assert target.getvalue() == b""


def test_packager_binds_every_recipe_before_publishing_the_header() -> None:
    binding_calls: list[bytes] = []
    encoding_calls = 0

    class RejectingExtension:
        extension_id = "org.example/rejecting@1"
        kind = ExtensionKind.STAGE
        descriptor = ExtensionDescriptor()

        def bind_encoder(self, parameters: bytes, /) -> Self:
            binding_calls.append(parameters)
            if parameters == b"bad":
                raise ProviderRejectedError("bad parameters")
            return self

        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            nonlocal encoding_calls
            encoding_calls += 1
            return data

    registry = ExtensionRegistry((RejectingExtension(),))
    good = RecipeSpec((StageSpec(RejectingExtension.extension_id, b"good"),))
    bad = RecipeSpec((StageSpec(RejectingExtension.extension_id, b"bad"),))
    target = io.BytesIO()

    with pytest.raises(PipelineError, match="bad parameters"):
        _package(
            target,
            registry,
            (_source(b"first", recipe=good), _source(b"second", recipe=bad)),
        )

    assert binding_calls == [b"good", b"bad"]
    assert encoding_calls == 0
    assert target.getvalue() == b""


def test_packager_rejects_a_missing_stage_before_publishing_the_header() -> None:
    target = io.BytesIO()
    source = _source(
        b"payload",
        recipe=RecipeSpec((StageSpec("org.example/missing@1"),)),
    )

    with pytest.raises(MissingStageError):
        _package(target, _stage_registry(), (source,))

    assert target.getvalue() == b""


def test_packager_stage_budget_spans_all_source_chunks() -> None:
    source = _source(b"ab", chunk_size=1)

    with pytest.raises(ResourceLimitError) as error:
        _package(
            io.BytesIO(),
            _stage_registry(),
            (source,),
            limits=ResourceLimits(max_stage_executions=1),
        )

    assert error.value.resource == "stage_executions"
    assert error.value.observed == 2


@pytest.mark.parametrize(
    ("limits", "resource"),
    [
        (ResourceLimits(max_chunks=0), "chunks"),
        (ResourceLimits(max_total_logical_bytes=0), "logical_bytes"),
    ],
)
def test_packager_refuses_known_operation_limits_before_stage_execution(
    limits: ResourceLimits,
    resource: str,
) -> None:
    encoding_calls = 0

    class CountingExtension:
        extension_id = "org.example/counting-output@1"
        kind = ExtensionKind.STAGE
        descriptor = ExtensionDescriptor()

        def bind_encoder(self, parameters: bytes, /) -> Self:
            return self

        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            nonlocal encoding_calls
            encoding_calls += 1
            return data

    registry = ExtensionRegistry((CountingExtension(),))
    source = _source(
        b"payload",
        recipe=RecipeSpec((StageSpec(CountingExtension.extension_id),)),
    )

    with pytest.raises(ResourceLimitError) as error:
        _package(io.BytesIO(), registry, (source,), limits=limits)

    assert error.value.resource == resource
    assert error.value.observed == (1 if resource == "chunks" else len(b"payl"))
    assert encoding_calls == 0


def test_packager_rejects_missing_or_repeated_sources_before_writing() -> None:
    empty_target = io.BytesIO()

    with pytest.raises(PackagingError, match="at least one"):
        _package(empty_target, _stage_registry(), ())
    assert empty_target.getvalue() == b""

    source = _source(b"payload")
    repeated_target = io.BytesIO()
    with pytest.raises(PackagingError, match="cannot be declared twice"):
        _package(repeated_target, _stage_registry(), (source, source))
    assert repeated_target.getvalue() == b""


def test_package_result_contains_no_carrier_or_publication_facts() -> None:
    assert [field.name for field in fields(PackageResult)] == [
        "manifest",
        "encoded_size",
        "chunk_count",
        "streams",
    ]


def test_packager_serializes_only_available_specification_urls() -> None:
    registry = _stage_registry()
    result = _package(
        io.BytesIO(),
        registry,
        (_source(b"payload", stream_type=_CUSTOM_STREAM_TYPE),),
    )

    specification_urls = {
        extension.extension_id: extension.specification_url
        for extension in result.manifest.extensions
    }
    assert specification_urls == {
        RawExtension.extension_id: RawExtension.descriptor.specification_url,
        _CUSTOM_STREAM_TYPE: None,
    }


def test_runtime_extension_ids_never_enter_the_manifest() -> None:
    class RuntimeCarrier:
        extension_id = "org.example/filesystem@1"
        kind = ExtensionKind.CARRIER
        descriptor = ExtensionDescriptor(
            specification_url="https://example.org/runtime/filesystem"
        )

    class RuntimePackager:
        extension_id = "org.example/fixed@1"
        kind = ExtensionKind.PACKAGER
        descriptor = ExtensionDescriptor(
            specification_url="https://example.org/runtime/fixed"
        )

    registry = ExtensionRegistry(
        (
            RawExtension(),
            RuntimeCarrier(),
            RuntimePackager(),
        )
    )

    result = _package(io.BytesIO(), registry, (_source(b"payload"),))

    assert tuple(
        extension.extension_id for extension in result.manifest.extensions
    ) == (BYTES_STREAM_TYPE, RawExtension.extension_id)


def test_registered_stream_profile_contributes_its_specification_url() -> None:
    class RecordsProfile:
        extension_id = _CUSTOM_STREAM_TYPE
        kind = ExtensionKind.STREAM_PROFILE
        descriptor = ExtensionDescriptor(
            specification_url="https://example.org/obst/records-v1"
        )

    profile = RecordsProfile()
    registry = ExtensionRegistry(
        (
            RawExtension(),
            Delta8Extension(),
            ZlibExtension(),
            profile,
        )
    )

    result = _package(
        io.BytesIO(),
        registry,
        (_source(b"payload", stream_type=_CUSTOM_STREAM_TYPE),),
    )

    specification_urls = {
        extension.extension_id: extension.specification_url
        for extension in result.manifest.extensions
    }
    assert (
        specification_urls[_CUSTOM_STREAM_TYPE] == profile.descriptor.specification_url
    )
