# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
from collections.abc import Buffer, Iterator
from io import BytesIO
from pathlib import Path
from typing import Protocol, cast

import pytest
from obst.core import (
    BYTES_STREAM_TYPE,
    BinaryWriter,
    BoundCarrierWriter,
    CarrierCapability,
    ExtensionRegistry,
    LogicalStreamDescriptor,
    LogicalStreamSource,
    PackageWriteOperation,
    RecipeSpec,
)

from obst_defaults.carriers import (
    CarrierError,
    CarrierStateError,
    PublicationReceipt,
    publish_package,
    write_package,
)
from obst_defaults.carriers.filesystem import (
    FilesystemCarrierExtension,
    FilesystemPublisherSession,
    FilesystemPublishRequest,
    FilesystemReadRequest,
)
from obst_defaults.carriers.memory import (
    MemoryCarrierExtension,
    MemoryPublisherSession,
    MemoryPublishRequest,
    MemoryReadRequest,
)
from obst_defaults.carriers.stdin import StdinCarrierExtension, StdinReadRequest
from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)
from support_resources import accounting as _accounting

_IDENTITY = RecipeSpec(())


def _filesystem_publisher(target: Path) -> FilesystemPublisherSession:
    return FilesystemPublisherSession(FilesystemPublishRequest(target))


def _memory_publisher() -> MemoryPublisherSession:
    return MemoryPublisherSession(MemoryPublishRequest())


class _SyncWriter(Protocol):
    def flush(self) -> None: ...

    def fileno(self) -> int: ...

    def close(self) -> None: ...


class _CloseFailsOnce:
    def __init__(self, delegate: _SyncWriter) -> None:
        self._delegate = delegate
        self._failed = False

    def flush(self) -> None:
        self._delegate.flush()

    def fileno(self) -> int:
        return self._delegate.fileno()

    def close(self) -> None:
        if not self._failed:
            self._failed = True
            raise OSError("close failed")
        self._delegate.close()


class _PartialOpenCarrier:
    def __init__(self, *, abort_error: BaseException | None = None) -> None:
        self.allocated = False
        self.abort_calls = 0
        self.abort_error = abort_error
        self.open_error = RuntimeError("open failed after allocation")

    def open(self) -> BinaryWriter:
        self.allocated = True
        raise self.open_error

    def commit(self) -> PublicationReceipt[str]:
        raise AssertionError("commit must not run after open failure")

    def abort(self) -> None:
        self.abort_calls += 1
        self.allocated = False
        if self.abort_error is not None:
            raise self.abort_error


class _CommitFailsCarrier:
    def __init__(self, *, abort_error: BaseException | None = None) -> None:
        self.buffer = BytesIO()
        self.abort_calls = 0
        self.abort_error = abort_error
        self.commit_error = RuntimeError("commit failed")

    def open(self) -> BinaryWriter:
        return self.buffer

    def commit(self) -> PublicationReceipt[str]:
        raise self.commit_error

    def abort(self) -> None:
        self.abort_calls += 1
        self.buffer.close()
        if self.abort_error is not None:
            raise self.abort_error


class _MemoryCloseFailsOnce:
    def __init__(self, delegate: BytesIO) -> None:
        self._delegate = delegate
        self._failed = False

    def getvalue(self) -> bytes:
        return self._delegate.getvalue()

    def close(self) -> None:
        if not self._failed:
            self._failed = True
            raise OSError("memory close failed")
        self._delegate.close()


class _WriteFailsCarrier:
    def __init__(self) -> None:
        self.abort_calls = 0
        self.write_error = OSError("write failed")

    def open(self) -> BinaryWriter:
        carrier = self

        class FailingWriter:
            def write(self, data: Buffer, /) -> int:
                raise carrier.write_error

        return FailingWriter()

    def commit(self) -> PublicationReceipt[str]:
        raise AssertionError("commit must not run after write failure")

    def abort(self) -> None:
        self.abort_calls += 1


class _StringPublicationCarrier:
    def __init__(self) -> None:
        self.buffer = BytesIO()

    def open(self) -> BinaryWriter:
        return self.buffer

    def commit(self) -> str:
        self.buffer.close()
        return "published"

    def abort(self) -> None:
        self.buffer.close()


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry(())


def _sources() -> tuple[LogicalStreamSource, ...]:
    descriptor = LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"carrier-test", _IDENTITY)
    return (
        LogicalStreamSource.from_bytes(
            descriptor,
            bytes(range(256)) * 8,
            chunk_size=127,
        ),
    )


def _fixed_operation(
    registry: ExtensionRegistry,
    sources: tuple[LogicalStreamSource, ...],
) -> PackageWriteOperation:
    return FixedPackagerExtension().prepare_package(
        FixedPackageRequest(registry, sources, _accounting())
    )


def test_carrier_extensions_resolve_through_the_common_registry() -> None:
    filesystem = FilesystemCarrierExtension()
    memory = MemoryCarrierExtension()
    stdin = StdinCarrierExtension()
    registry = ExtensionRegistry((stdin, memory, filesystem))

    assert (
        registry.require_carrier_reader_provider(filesystem.extension_id) is filesystem
    )
    assert (
        registry.require_carrier_publisher_provider(filesystem.extension_id)
        is filesystem
    )
    assert registry.require_carrier_reader_provider(memory.extension_id) is memory
    assert registry.require_carrier_publisher_provider(memory.extension_id) is memory
    assert registry.require_carrier_reader_provider(stdin.extension_id) is stdin
    assert registry.get_carrier_publisher_provider(stdin.extension_id) is None
    capabilities = registry.capabilities()
    assert all(isinstance(capability, CarrierCapability) for capability in capabilities)
    assert tuple(capability.extension_id for capability in capabilities) == (
        filesystem.extension_id,
        memory.extension_id,
        stdin.extension_id,
    )


def test_filesystem_reader_uses_one_bound_handle(tmp_path: Path) -> None:
    path = tmp_path / "input.obst"
    path.write_bytes(b"container bytes")
    session = FilesystemCarrierExtension().bind_reader(FilesystemReadRequest(path))

    source = session.open()

    assert source.read(100) == b"container bytes"
    session.close()
    with pytest.raises(CarrierStateError, match="closed state"):
        session.open()


def test_memory_and_stdin_read_sessions_preserve_ownership() -> None:
    memory = MemoryCarrierExtension().bind_reader(MemoryReadRequest(b"memory"))
    memory_source = memory.open()
    assert memory_source.read(100) == b"memory"
    memory.close()

    host_source = BytesIO(b"stdin")
    stdin = StdinCarrierExtension().bind_reader(StdinReadRequest(host_source))
    assert stdin.open().read(100) == b"stdin"
    stdin.close()
    assert not host_source.closed


def test_streaming_writer_contract_does_not_promise_rollback() -> None:
    class StreamingSession:
        def __init__(self) -> None:
            self.buffer = BytesIO()

        def open(self) -> BinaryWriter:
            return self.buffer

        def finish(self) -> bytes:
            return self.buffer.getvalue()

        def close(self) -> None:
            self.buffer.close()

    session = StreamingSession()

    assert isinstance(session, BoundCarrierWriter)
    assert not hasattr(session, "abort")


def test_write_package_returns_streaming_completion_and_closes_carrier() -> None:
    class VisibleWriter:
        def __init__(self) -> None:
            self.data = bytearray()

        def write(self, data: Buffer, /) -> int:
            encoded = bytes(data)
            self.data.extend(encoded)
            return len(encoded)

    class StreamingSession:
        def __init__(self) -> None:
            self.writer = VisibleWriter()
            self.closed = False

        def open(self) -> BinaryWriter:
            return self.writer

        def finish(self) -> bytes:
            return bytes(self.writer.data)

        def close(self) -> None:
            self.closed = True

    session = StreamingSession()

    written = write_package(
        _fixed_operation(_stage_registry(), _sources()),
        session,
    )

    assert written.completion == bytes(session.writer.data)
    assert written.package.encoded_size == len(written.completion)
    assert session.closed


def test_streaming_failure_leaves_visible_prefix_and_closes_without_rollback() -> None:
    class VisibleWriter:
        def __init__(self) -> None:
            self.data = bytearray()

        def write(self, data: Buffer, /) -> int:
            encoded = bytes(data)
            self.data.extend(encoded)
            return len(encoded)

    class StreamingSession:
        def __init__(self) -> None:
            self.writer = VisibleWriter()
            self.closed = False

        def open(self) -> BinaryWriter:
            return self.writer

        def finish(self) -> None:
            raise AssertionError("finish must not follow a write failure")

        def close(self) -> None:
            self.closed = True

    def failing_chunks() -> Iterator[bytes]:
        yield b"visible"
        raise RuntimeError("source failed")

    source = LogicalStreamSource(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", _IDENTITY),
        failing_chunks(),
        max_chunk_bytes=len(b"visible"),
    )
    session = StreamingSession()

    with pytest.raises(RuntimeError, match="source failed"):
        write_package(
            _fixed_operation(_stage_registry(), (source,)),
            session,
        )

    assert session.writer.data
    assert session.closed
    assert not hasattr(session, "abort")


def test_memory_and_filesystem_carriers_publish_identical_container_bytes(
    tmp_path: Path,
) -> None:
    memory = publish_package(
        _fixed_operation(_stage_registry(), _sources()),
        _memory_publisher(),
    )
    target = tmp_path / "payload.obst"
    filesystem = publish_package(
        _fixed_operation(_stage_registry(), _sources()),
        _filesystem_publisher(target),
    )

    assert target.read_bytes() == memory.publication.reference
    assert filesystem.publication.reference == target
    assert filesystem.package == memory.package
    assert filesystem.package.encoded_size == target.stat().st_size


def test_publish_package_preserves_arbitrary_publication_result() -> None:
    published = publish_package(
        _fixed_operation(_stage_registry(), _sources()),
        _StringPublicationCarrier(),
    )

    assert published.publication == "published"
    assert published.package.encoded_size > 0


def test_failed_package_never_publishes_partial_filesystem_destination(
    tmp_path: Path,
) -> None:
    target = tmp_path / "failed.obst"

    def failing_chunks() -> Iterator[bytes]:
        yield b"published only to the temporary target"
        raise RuntimeError("source failed")

    source = LogicalStreamSource(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", _IDENTITY),
        failing_chunks(),
        max_chunk_bytes=len(b"published only to the temporary target"),
    )

    with pytest.raises(RuntimeError, match="source failed"):
        publish_package(
            _fixed_operation(_stage_registry(), (source,)),
            _filesystem_publisher(target),
        )

    assert not target.exists()
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_write_failure_aborts_before_commit_and_preserves_primary_error() -> None:
    carrier = _WriteFailsCarrier()

    with pytest.raises(OSError) as error:
        publish_package(_fixed_operation(_stage_registry(), _sources()), carrier)

    assert error.value is carrier.write_error
    assert carrier.abort_calls == 1


def test_open_failure_triggers_exactly_one_abort_and_preserves_primary_error() -> None:
    carrier = _PartialOpenCarrier()

    with pytest.raises(RuntimeError) as error:
        publish_package(_fixed_operation(_stage_registry(), _sources()), carrier)

    assert error.value is carrier.open_error
    assert carrier.abort_calls == 1
    assert not carrier.allocated


def test_open_failure_retains_abort_failure_as_secondary_note() -> None:
    carrier = _PartialOpenCarrier(abort_error=OSError("abort failed"))

    with pytest.raises(RuntimeError) as error:
        publish_package(_fixed_operation(_stage_registry(), _sources()), carrier)

    assert error.value is carrier.open_error
    assert error.value.__notes__ == ["carrier abort also failed: abort failed"]
    assert carrier.abort_calls == 1
    assert not carrier.allocated


def test_commit_failure_triggers_exactly_one_abort_and_preserves_primary() -> None:
    carrier = _CommitFailsCarrier()

    with pytest.raises(RuntimeError) as error:
        publish_package(_fixed_operation(_stage_registry(), _sources()), carrier)

    assert error.value is carrier.commit_error
    assert carrier.abort_calls == 1
    assert carrier.buffer.closed


def test_commit_failure_retains_abort_failure_as_secondary_note() -> None:
    carrier = _CommitFailsCarrier(abort_error=OSError("abort failed"))

    with pytest.raises(RuntimeError) as error:
        publish_package(_fixed_operation(_stage_registry(), _sources()), carrier)

    assert error.value is carrier.commit_error
    assert error.value.__notes__ == ["carrier abort also failed: abort failed"]
    assert carrier.abort_calls == 1


def test_filesystem_carrier_refuses_overwrite_without_touching_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.obst"
    target.write_bytes(b"keep")

    with pytest.raises(CarrierError, match="already exists"):
        publish_package(
            _fixed_operation(_stage_registry(), _sources()),
            _filesystem_publisher(target),
        )

    assert target.read_bytes() == b"keep"
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_filesystem_carrier_explicit_overwrite_replaces_complete_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.obst"
    target.write_bytes(b"old")
    carrier = FilesystemPublisherSession(
        FilesystemPublishRequest(target, overwrite=True)
    )
    writer = carrier.open()
    assert writer.write(b"complete replacement") == len(b"complete replacement")

    receipt = carrier.commit()

    assert receipt.reference == target
    assert receipt.cleanup_issues == ()
    assert target.read_bytes() == b"complete replacement"
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_filesystem_open_failure_is_terminal_even_without_publish_helper(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.obst"
    target.write_bytes(b"keep")
    carrier = _filesystem_publisher(target)

    with pytest.raises(CarrierError, match="already exists"):
        carrier.open()

    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.open()
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.commit()
    carrier.abort()
    assert target.read_bytes() == b"keep"


def test_filesystem_commit_refuses_target_created_after_open(
    tmp_path: Path,
) -> None:
    target = tmp_path / "raced.obst"
    carrier = _filesystem_publisher(target)
    writer = carrier.open()
    assert writer.write(b"new") == 3
    target.write_bytes(b"keep")

    with pytest.raises(CarrierError, match="refusing to overwrite"):
        carrier.commit()

    assert target.read_bytes() == b"keep"
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_filesystem_commit_reports_cleanup_after_successful_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "committed.obst"
    carrier = _filesystem_publisher(target)
    writer = carrier.open()
    assert writer.write(b"complete") == 8
    temporary_path = next(tmp_path.glob(f".{target.name}.*.tmp"))
    original_unlink = Path.unlink

    def fail_temporary_cleanup(path: Path, missing_ok: bool = False) -> None:
        if path == temporary_path:
            raise OSError("cleanup failed")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_temporary_cleanup)

    receipt = carrier.commit()

    assert receipt.reference == target
    assert receipt.cleanup_issues[0].resource == str(temporary_path)
    assert receipt.cleanup_issues[0].reason == "cleanup failed"
    assert target.read_bytes() == b"complete"
    assert temporary_path.read_bytes() == b"complete"
    with pytest.raises(CarrierStateError, match="committed state"):
        carrier.abort()


def test_filesystem_no_overwrite_publication_exposes_only_complete_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "atomic.obst"
    carrier = _filesystem_publisher(target)
    writer = carrier.open()
    payload = bytes(range(256)) * 32
    assert writer.write(payload) == len(payload)
    original_link = os.link

    def observe_link(source: Path, destination: Path) -> None:
        assert not destination.exists()
        assert Path(source).read_bytes() == payload
        original_link(source, destination)
        assert Path(destination).read_bytes() == payload

    monkeypatch.setattr(
        "obst_defaults.carriers.filesystem.os.link",
        observe_link,
    )

    receipt = carrier.commit()

    assert receipt.cleanup_issues == ()
    assert target.read_bytes() == payload


def test_filesystem_no_overwrite_fails_closed_without_hard_link_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "unsupported.obst"
    carrier = _filesystem_publisher(target)
    writer = carrier.open()
    assert writer.write(b"payload") == 7

    def reject_link(source: Path, destination: Path) -> None:
        raise OSError("hard links unsupported")

    monkeypatch.setattr(
        "obst_defaults.carriers.filesystem.os.link",
        reject_link,
    )

    with pytest.raises(CarrierError, match="hard links unsupported"):
        carrier.commit()

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_carrier_lifecycle_rejects_invalid_transitions(tmp_path: Path) -> None:
    memory = _memory_publisher()
    memory.open()
    with pytest.raises(CarrierError, match="cannot open"):
        memory.open()
    receipt = memory.commit()
    assert receipt.reference == b""
    with pytest.raises(CarrierError, match="cannot commit"):
        memory.commit()
    with pytest.raises(CarrierStateError, match="committed state") as error:
        memory.abort()
    assert error.value.operation == "abort"
    assert error.value.state == "committed"

    filesystem = _filesystem_publisher(tmp_path / "aborted.obst")
    filesystem.open()
    filesystem.abort()
    filesystem.abort()
    with pytest.raises(CarrierError, match="cannot commit"):
        filesystem.commit()
    assert list(tmp_path.iterdir()) == []


def test_memory_commit_failure_is_terminal_and_never_returns_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _memory_publisher()
    writer = carrier.open()
    assert writer.write(b"payload") == 7
    monkeypatch.setattr(
        carrier,
        "_buffer",
        cast(BytesIO, _MemoryCloseFailsOnce(cast(BytesIO, writer))),
    )

    with pytest.raises(CarrierError, match="memory close failed") as error:
        carrier.commit()

    assert isinstance(error.value.__cause__, OSError)
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.commit()
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.open()
    carrier.abort()


def test_memory_open_failure_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _memory_publisher()
    allocation_error = MemoryError("allocation failed")

    def fail_allocation() -> BytesIO:
        raise allocation_error

    monkeypatch.setattr(
        "obst_defaults.carriers.memory.BytesIO",
        fail_allocation,
    )

    with pytest.raises(MemoryError) as error:
        carrier.open()

    assert error.value is allocation_error
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.open()
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.commit()
    carrier.abort()


def test_memory_abort_failure_enters_cleanup_required_until_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _memory_publisher()
    writer = carrier.open()
    monkeypatch.setattr(
        carrier,
        "_buffer",
        cast(BytesIO, _MemoryCloseFailsOnce(cast(BytesIO, writer))),
    )

    with pytest.raises(CarrierError, match="memory close failed"):
        carrier.abort()

    with pytest.raises(CarrierStateError, match="cleanup_required state"):
        carrier.open()
    with pytest.raises(CarrierStateError, match="cleanup_required state"):
        carrier.commit()
    carrier.abort()
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.commit()


def test_filesystem_commit_preserves_fsync_failure_and_discards_temporary_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _filesystem_publisher(tmp_path / "failed.obst")
    writer = carrier.open()
    assert writer.write(b"payload") == 7

    def fail_fsync(file_descriptor: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr("obst_defaults.carriers.filesystem.os.fsync", fail_fsync)

    with pytest.raises(CarrierError) as error:
        carrier.commit()

    assert str(error.value) == "cannot commit output carrier: fsync failed"
    assert isinstance(error.value.__cause__, OSError)
    assert str(error.value.__cause__) == "fsync failed"
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.open()
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.commit()
    carrier.abort()


def test_filesystem_commit_cleans_before_rethrowing_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StopPublication(BaseException):
        pass

    carrier = _filesystem_publisher(tmp_path / "interrupted.obst")
    writer = carrier.open()
    assert writer.write(b"payload") == 7
    interruption = StopPublication("stop now")

    def interrupt_fsync(file_descriptor: int) -> None:
        raise interruption

    monkeypatch.setattr(
        "obst_defaults.carriers.filesystem.os.fsync",
        interrupt_fsync,
    )

    with pytest.raises(StopPublication) as error:
        carrier.commit()

    assert error.value is interruption
    assert list(tmp_path.iterdir()) == []
    carrier.abort()


def test_filesystem_commit_recovers_after_a_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _filesystem_publisher(tmp_path / "failed.obst")
    writer = carrier.open()
    assert writer.write(b"payload") == 7
    monkeypatch.setattr(
        carrier,
        "_file",
        _CloseFailsOnce(cast(_SyncWriter, writer)),
    )

    with pytest.raises(CarrierError) as error:
        carrier.commit()

    assert str(error.value) == "cannot commit output carrier: close failed"
    assert isinstance(error.value.__cause__, OSError)
    assert list(tmp_path.iterdir()) == []
    carrier.abort()


def test_filesystem_abort_failure_keeps_cleanup_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _filesystem_publisher(tmp_path / "aborted.obst")
    writer = carrier.open()
    assert writer.write(b"payload") == 7
    temporary_path = next(tmp_path.glob(".aborted.obst.*.tmp"))
    monkeypatch.setattr(
        carrier,
        "_file",
        _CloseFailsOnce(cast(_SyncWriter, writer)),
    )
    original_unlink = Path.unlink
    unlink_failed = False

    def fail_unlink_once(path: Path, missing_ok: bool = False) -> None:
        nonlocal unlink_failed
        if path == temporary_path and not unlink_failed:
            unlink_failed = True
            raise OSError("unlink failed")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink_once)

    with pytest.raises(CarrierError) as error:
        carrier.abort()

    assert str(error.value) == "cannot abort output carrier: close failed"
    assert isinstance(error.value.__cause__, OSError)
    assert error.value.__notes__ == [
        "carrier cleanup also failed: OSError: unlink failed"
    ]
    with pytest.raises(CarrierStateError, match="cleanup_required state"):
        carrier.commit()

    carrier.abort()
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(CarrierStateError, match="aborted state"):
        carrier.commit()
