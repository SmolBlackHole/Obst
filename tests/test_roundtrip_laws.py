from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from typing import Never

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ContainerWriter,
    ExtensionKind,
    ExtensionRegistry,
    Manifest,
    Recipe,
    ResourceLimits,
    StageCodecProvider,
    StageExtension,
    StageSpec,
    Stream,
    decode_recipe,
    encode_chunk_once,
    encode_recipe,
    inspect_container,
    iter_decoded_chunks,
    materialize_stream,
)
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import (
    ZlibDictionaryExtension,
    ZlibDictionaryParameters,
    ZlibExtension,
    ZlibParameters,
)
from obst_defaults.transforms.delta8 import Delta8Extension

_LOGICAL_STREAM_TYPE = "org.example/logical-bytes@1"
_RAW = RawExtension()
_DELTA8 = Delta8Extension()
_ZLIB = ZlibExtension()
_ZLIB_DICTIONARY = ZlibDictionaryExtension()
_CONTAINER_RECIPES = (
    Recipe(0, (StageSpec(RawExtension.extension_id),)),
    Recipe(1, (StageSpec(Delta8Extension.extension_id),)),
    Recipe(2, (StageSpec(ZlibExtension.extension_id, b"\x06"),)),
    Recipe(
        3,
        (
            StageSpec(Delta8Extension.extension_id),
            StageSpec(ZlibExtension.extension_id, b"\x09"),
            StageSpec(RawExtension.extension_id),
        ),
    ),
)


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry(
        (
            _RAW,
            _DELTA8,
            _ZLIB,
            _ZLIB_DICTIONARY,
        )
    )


def _assert_recipe_reverse_law(data: bytes, recipe: Recipe) -> None:
    registry = _stage_registry()
    encode_budget = max(len(data) + 64, 64)
    encoded = encode_recipe(
        data,
        recipe,
        registry,
        limits=ResourceLimits(max_intermediate_bytes=encode_budget),
    )

    decoded = decode_recipe(
        encoded,
        recipe,
        registry,
        expected_size=len(data),
        limits=ResourceLimits(
            max_intermediate_bytes=max(encode_budget, len(encoded)),
        ),
    )

    assert decoded == data
    assert (
        encode_recipe(
            data,
            recipe,
            registry,
            limits=ResourceLimits(max_intermediate_bytes=encode_budget),
        )
        == encoded
    )


@pytest.mark.parametrize(
    ("extension", "expected_id"),
    [
        (_RAW, "obst.raw@1"),
        (_DELTA8, "obst.delta8@1"),
        (_ZLIB, "obst.zlib@1"),
        (_ZLIB_DICTIONARY, "obst.zlib@2"),
    ],
)
def test_first_party_stage_owns_identity_and_capabilities(
    extension: StageExtension,
    expected_id: str,
) -> None:
    assert extension.extension_id == expected_id
    assert extension.kind is ExtensionKind.STAGE
    assert extension.descriptor.specification_url is not None
    assert isinstance(extension, StageCodecProvider)


@pytest.mark.parametrize(
    ("extension", "parameters", "payload"),
    [
        (_RAW, b"", bytes(range(256))),
        (_DELTA8, b"", bytes(range(256)) * 4),
        (_ZLIB, b"\x09", b"fruit" * 1024),
        (
            _ZLIB_DICTIONARY,
            _ZLIB_DICTIONARY.encode_parameters(
                ZlibDictionaryParameters(9, b"common-prefix:")
            ),
            b"common-prefix:one/common-prefix:two" * 128,
        ),
    ],
)
def test_first_party_bound_codecs_are_reentrant_and_deterministic(
    extension: StageCodecProvider,
    parameters: bytes,
    payload: bytes,
) -> None:
    encoder = extension.bind_encoder(parameters)
    decoder = extension.bind_decoder(parameters)

    expected_encoded = encoder.encode(payload, max_output_size=None)
    expected_decoded = decoder.decode(expected_encoded, max_output_size=None)

    def encode_once(_: int) -> bytes:
        return encoder.encode(payload, max_output_size=None)

    def decode_once(_: int) -> bytes:
        return decoder.decode(expected_encoded, max_output_size=None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        encoded_results = tuple(pool.map(encode_once, range(32)))
        decoded_results = tuple(pool.map(decode_once, range(32)))

    assert expected_decoded == payload
    assert encoded_results == (expected_encoded,) * 32
    assert decoded_results == (payload,) * 32


@pytest.mark.parametrize(
    ("extension", "parameters"),
    [
        (_ZLIB, b"\x09"),
        (
            _ZLIB_DICTIONARY,
            _ZLIB_DICTIONARY.encode_parameters(
                ZlibDictionaryParameters(9, b"common-prefix:")
            ),
        ),
    ],
)
def test_zlib_bound_executors_do_not_reparse_parameters(
    monkeypatch: pytest.MonkeyPatch,
    extension: StageCodecProvider,
    parameters: bytes,
) -> None:
    encoder = extension.bind_encoder(parameters)
    decoder = extension.bind_decoder(parameters)

    def fail_if_reparsed(*args: object, **kwargs: object) -> Never:
        raise AssertionError("bound executor reparsed its parameters")

    monkeypatch.setattr(type(extension), "decode_parameters", fail_if_reparsed)

    payload = b"common-prefix:one/common-prefix:two" * 8
    encoded = encoder.encode(payload, max_output_size=None)
    assert encoder.encode(payload, max_output_size=None) == encoded
    assert decoder.decode(encoded, max_output_size=None) == payload
    assert decoder.decode(encoded, max_output_size=None) == payload


@pytest.mark.parametrize("compression_level", range(10))
def test_zlib_extension_authors_its_parameter_bytes(
    compression_level: int,
) -> None:
    value = ZlibParameters(compression_level)
    assert _ZLIB.encode_parameters(value) == bytes((compression_level,))
    assert _ZLIB.decode_parameters(bytes((compression_level,))) == value


def test_zlib_dictionary_extension_authors_its_parameter_bytes() -> None:
    dictionary = b"common-prefix:"

    value = ZlibDictionaryParameters(7, dictionary)
    assert _ZLIB_DICTIONARY.encode_parameters(value) == b"\x07" + dictionary
    assert _ZLIB_DICTIONARY.decode_parameters(b"\x07" + dictionary) == value


@pytest.mark.parametrize(
    "stage_id",
    [RawExtension.extension_id, Delta8Extension.extension_id],
)
@settings(max_examples=40)
@example(data=b"")
@example(data=b"x")
@example(data=bytes(range(256)))
@given(data=st.binary(max_size=4096))
def test_parameterless_stage_reverse_law(data: bytes, stage_id: str) -> None:
    _assert_recipe_reverse_law(data, Recipe(0, (StageSpec(stage_id),)))


@pytest.mark.parametrize("compression_level", range(10))
@settings(max_examples=30)
@example(data=b"")
@example(data=b"x")
@example(data=bytes(range(256)))
@given(data=st.binary(max_size=4096))
def test_zlib_stage_reverse_law(data: bytes, compression_level: int) -> None:
    recipe = Recipe(
        0,
        (
            StageSpec(
                ZlibExtension.extension_id,
                _ZLIB.encode_parameters(ZlibParameters(compression_level)),
            ),
        ),
    )
    _assert_recipe_reverse_law(data, recipe)

    encoded = encode_recipe(
        data,
        recipe,
        _stage_registry(),
        limits=ResourceLimits(max_intermediate_bytes=max(len(data) + 64, 64)),
    )
    assert encoded[1] & 0x20 == 0


@settings(max_examples=50)
@example(data=b"", dictionary=b"x", compression_level=0)
@example(
    data=b"common-prefix:one/common-prefix:two",
    dictionary=b"common-prefix:",
    compression_level=9,
)
@given(
    data=st.binary(max_size=4096),
    dictionary=st.binary(min_size=1, max_size=1024),
    compression_level=st.integers(min_value=0, max_value=9),
)
def test_zlib_dictionary_stage_reverse_law(
    data: bytes,
    dictionary: bytes,
    compression_level: int,
) -> None:
    parameters = _ZLIB_DICTIONARY.encode_parameters(
        ZlibDictionaryParameters(compression_level, dictionary)
    )
    recipe = Recipe(
        0,
        (StageSpec(ZlibDictionaryExtension.extension_id, parameters),),
    )
    _assert_recipe_reverse_law(data, recipe)

    encoded = encode_recipe(
        data,
        recipe,
        _stage_registry(),
        limits=ResourceLimits(max_intermediate_bytes=max(len(data) + 64, 64)),
    )
    assert encoded[1] & 0x20


@settings(max_examples=40)
@example(data=b"", compression_level=0)
@example(data=bytes(range(256)), compression_level=9)
@given(
    data=st.binary(max_size=4096),
    compression_level=st.integers(min_value=0, max_value=9),
)
def test_composed_recipe_reverse_law(data: bytes, compression_level: int) -> None:
    _assert_recipe_reverse_law(
        data,
        Recipe(
            0,
            (
                StageSpec(Delta8Extension.extension_id),
                StageSpec(
                    ZlibExtension.extension_id,
                    _ZLIB.encode_parameters(ZlibParameters(compression_level)),
                ),
                StageSpec(RawExtension.extension_id),
            ),
        ),
    )


@settings(max_examples=60)
@example(
    streams=[
        (b"", b"empty", 0),
        (b"x", b"delta", 1),
        (b"abcde", b"zlib", 2),
        (bytes(range(16)), b"pipeline", 3),
    ],
    chunk_size=4,
)
@given(
    streams=st.lists(
        st.tuples(
            st.binary(max_size=1024),
            st.binary(max_size=32),
            st.integers(min_value=0, max_value=len(_CONTAINER_RECIPES) - 1),
        ),
        min_size=1,
        max_size=4,
    ),
    chunk_size=st.integers(min_value=1, max_value=128),
)
def test_container_logical_dataset_reverse_law(
    streams: list[tuple[bytes, bytes, int]],
    chunk_size: int,
) -> None:
    manifest = Manifest(
        recipes=_CONTAINER_RECIPES,
        streams=tuple(
            Stream(
                stream_id,
                _LOGICAL_STREAM_TYPE,
                recipe_id,
                metadata,
            )
            for stream_id, (_, metadata, recipe_id) in enumerate(streams)
        ),
    )
    chunks_by_stream = tuple(
        tuple(
            payload[offset : offset + chunk_size]
            for offset in range(0, len(payload), chunk_size)
        )
        for payload, _, _ in streams
    )
    target = io.BytesIO()
    registry = _stage_registry()
    writer = ContainerWriter(target, manifest)
    expected_physical_order: list[tuple[int, int, bytes]] = []
    sequence_count = max((len(chunks) for chunks in chunks_by_stream), default=0)
    for sequence in range(sequence_count):
        for stream_id, chunks in enumerate(chunks_by_stream):
            if sequence < len(chunks):
                logical_chunk = chunks[sequence]
                recipe_id = manifest.stream(stream_id).default_recipe_id
                writer.write_chunk(
                    encode_chunk_once(
                        logical_chunk,
                        stream_id=stream_id,
                        sequence=sequence,
                        recipe=manifest.recipe(recipe_id),
                        registry=registry,
                    )
                )
                expected_physical_order.append((stream_id, sequence, logical_chunk))
    writer.finish()
    encoded = target.getvalue()

    reader = ContainerReader(io.BytesIO(encoded))
    decoded_chunks = list(iter_decoded_chunks(reader, registry))
    recovered = [bytearray() for _ in streams]
    for encoded_chunk, logical_bytes in decoded_chunks:
        recovered[encoded_chunk.stream_id].extend(logical_bytes)

    assert [
        (chunk.stream_id, chunk.sequence, logical_bytes)
        for chunk, logical_bytes in decoded_chunks
    ] == expected_physical_order
    assert tuple(bytes(stream) for stream in recovered) == tuple(
        payload for payload, _, _ in streams
    )
    assert tuple(
        (stream.stream_type, stream.metadata) for stream in reader.manifest.streams
    ) == tuple((_LOGICAL_STREAM_TYPE, metadata) for _, metadata, _ in streams)


@settings(max_examples=30)
@example(payload=b"fruit all the way down", inner_chunk_size=5, outer_chunk_size=7)
@given(
    payload=st.binary(max_size=512),
    inner_chunk_size=st.integers(min_value=1, max_value=64),
    outer_chunk_size=st.integers(min_value=1, max_value=128),
)
def test_raw_in_raw_is_opaque_until_explicit_reverse_traversal(
    payload: bytes,
    inner_chunk_size: int,
    outer_chunk_size: int,
) -> None:
    inner = _write_raw_container(payload, chunk_size=inner_chunk_size)
    outer = _write_raw_container(inner, chunk_size=outer_chunk_size)

    inspection = inspect_container(ContainerReader(io.BytesIO(outer)))
    registry = _stage_registry()
    recovered_inner = materialize_stream(
        ContainerReader(io.BytesIO(outer)), 0, registry
    )

    assert inspection.logical_size == len(inner)
    assert recovered_inner == inner
    assert (
        materialize_stream(ContainerReader(io.BytesIO(recovered_inner)), 0, registry)
        == payload
    )


def _write_raw_container(payload: bytes, *, chunk_size: int) -> bytes:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec(RawExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    registry = _stage_registry()
    writer = ContainerWriter(target, manifest)
    for sequence, offset in enumerate(range(0, len(payload), chunk_size)):
        writer.write_chunk(
            encode_chunk_once(
                payload[offset : offset + chunk_size],
                stream_id=0,
                sequence=sequence,
                recipe=manifest.recipe(0),
                registry=registry,
            )
        )
    writer.finish()
    return target.getvalue()
