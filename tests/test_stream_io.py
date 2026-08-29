from __future__ import annotations

from collections.abc import Buffer
from typing import cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from obst.core import (
    BYTES_STREAM_TYPE,
    BinaryIOContractError,
    ContainerReader,
    ContainerWriter,
    ExtensionRegistry,
    InvalidContainerError,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
    TruncatedContainerError,
    encode_chunk_once,
    inspect_container,
    materialize_stream,
)
from obst.core.io import read_exact, write_all
from tests.support_extensions import IdentityExtension
from tests.support_resources import accounting as _accounting


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry((IdentityExtension(),))


def _identity_stage_manifest() -> Manifest:
    return Manifest(
        recipes=(Recipe(0, (StageSpec(IdentityExtension.extension_id),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )


class _ShortReader:
    def __init__(self, data: bytes, *, max_read: int) -> None:
        self._data = data
        self._offset = 0
        self._max_read = max_read

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._offset
        size = min(size, self._max_read)
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _StallingReader(_ShortReader):
    def __init__(self, data: bytes, *, stall_after: int) -> None:
        super().__init__(data, max_read=2)
        self._stall_after = stall_after
        self._stalled = False

    def read(self, size: int = -1) -> bytes:
        if not self._stalled and self._offset >= self._stall_after:
            self._stalled = True
            return b""
        return super().read(size)


class _PartialWriter:
    def __init__(self, *, max_write: int) -> None:
        self._data = bytearray()
        self._max_write = max_write

    def write(self, data: Buffer) -> int:
        view = memoryview(data)
        written = min(len(view), self._max_write)
        self._data.extend(view[:written])
        return written

    def getvalue(self) -> bytes:
        return bytes(self._data)


class _ZeroWriter:
    def write(self, data: Buffer) -> int:
        return 0


class _InvalidReader:
    def __init__(self, result: object) -> None:
        self._result = result
        self.requests: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        return cast(bytes, self._result)


class _InvalidWriter:
    def __init__(self, result: object) -> None:
        self._result = result
        self.offered_sizes: list[int] = []

    def write(self, data: Buffer) -> int:
        self.offered_sizes.append(len(memoryview(data)))
        return cast(int, self._result)


class _BytesSubclass(bytes):
    pass


def _encode(
    payload: bytes,
    *,
    max_write: int = 3,
    chunk_size: int = 4,
) -> bytes:
    target = _PartialWriter(max_write=max_write)
    manifest = _identity_stage_manifest()
    registry = _stage_registry()
    writer = ContainerWriter(target, manifest, accounting=_accounting())
    for sequence, offset in enumerate(range(0, len(payload), chunk_size)):
        writer.write_chunk(
            encode_chunk_once(
                payload[offset : offset + chunk_size],
                stream_id=0,
                sequence=sequence,
                recipe=manifest.recipe(0),
                registry=registry,
                accounting=_accounting(),
            )
        )
    writer.finish()
    return target.getvalue()


def test_container_uses_only_minimal_reader_and_writer_contracts() -> None:
    payload = b"minimal blocking protocols"

    encoded = _encode(payload)
    decoded = materialize_stream(
        ContainerReader(_ShortReader(encoded, max_read=2), accounting=_accounting()),
        0,
        _stage_registry(),
    )

    assert decoded == payload


@settings(max_examples=50)
@example(payload=b"", max_read=1, max_write=1, chunk_size=1)
@example(payload=b"x", max_read=1, max_write=1, chunk_size=4)
@example(payload=b"abcd", max_read=2, max_write=3, chunk_size=4)
@example(payload=b"abcde", max_read=2, max_write=3, chunk_size=4)
@given(
    payload=st.binary(max_size=1024),
    max_read=st.integers(min_value=1, max_value=64),
    max_write=st.integers(min_value=1, max_value=64),
    chunk_size=st.integers(min_value=1, max_value=128),
)
def test_reader_and_writer_accept_bounded_short_progress(
    payload: bytes,
    max_read: int,
    max_write: int,
    chunk_size: int,
) -> None:
    encoded = _encode(payload, max_write=max_write, chunk_size=chunk_size)

    inspection = inspect_container(
        ContainerReader(
            _ShortReader(encoded, max_read=max_read), accounting=_accounting()
        )
    )
    decoded = materialize_stream(
        ContainerReader(
            _ShortReader(encoded, max_read=max_read), accounting=_accounting()
        ),
        0,
        _stage_registry(),
    )

    assert inspection.chunk_count == (len(payload) + chunk_size - 1) // chunk_size
    assert decoded == payload


def test_clean_eof_is_only_accepted_after_terminal_commit() -> None:
    empty_container = _encode(b"")

    inspection = inspect_container(
        ContainerReader(
            _ShortReader(empty_container, max_read=1), accounting=_accounting()
        )
    )
    assert inspection.chunk_count == 0

    with pytest.raises(InvalidContainerError, match="trailing bytes"):
        inspect_container(
            ContainerReader(
                _ShortReader(empty_container + b"O", max_read=1),
                accounting=_accounting(),
            )
        )


def test_reader_treats_non_progress_as_truncation_without_retrying_forever() -> None:
    encoded = _encode(b"payload")

    with pytest.raises(TruncatedContainerError, match="container header"):
        ContainerReader(
            _StallingReader(encoded, stall_after=4), accounting=_accounting()
        )


def test_writer_rejects_non_progress() -> None:
    with pytest.raises(BinaryIOContractError, match="reported 0"):
        ContainerWriter(
            _ZeroWriter(), _identity_stage_manifest(), accounting=_accounting()
        )


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(None, id="none"),
        pytest.param("bytes", id="string"),
        pytest.param(bytearray(b"x"), id="bytearray"),
        pytest.param(_BytesSubclass(b"x"), id="bytes-subclass"),
        pytest.param(b"abcde", id="over-read"),
    ],
)
def test_reader_rejects_invalid_results_before_follow_up_reads(result: object) -> None:
    source = _InvalidReader(result)

    with pytest.raises(BinaryIOContractError) as captured:
        read_exact(source, 4, structure="test value")

    assert captured.value.endpoint == "reader"
    assert source.requests == [4]


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(None, id="none"),
        pytest.param(True, id="bool"),
        pytest.param("1", id="string"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(5, id="over-reported"),
    ],
)
def test_writer_rejects_invalid_progress_before_another_write(result: object) -> None:
    target = _InvalidWriter(result)

    with pytest.raises(BinaryIOContractError) as captured:
        write_all(target, b"data")

    assert captured.value.endpoint == "writer"
    assert target.offered_sizes == [4]


def test_one_byte_short_reads_reconstruct_into_one_bounded_result() -> None:
    payload = bytes(range(256)) * 256

    assert (
        read_exact(
            _ShortReader(payload, max_read=1),
            len(payload),
            structure="test payload",
        )
        == payload
    )
